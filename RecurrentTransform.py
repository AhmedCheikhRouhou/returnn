
from math import sqrt, pi
import theano
import theano.tensor as T
import theano.sandbox.cuda as cuda
import numpy
from MultiBatchBeam import multi_batch_beam


class RecurrentTransformBase(object):
  name = None

  def __init__(self, force_gpu=False, layer=None, for_custom=False):
    """
    :type layer: NetworkRecurrentLayer.RecurrentUnitLayer
    :param bool for_custom: When used with LSTMC + LSTMCustomOp, there are two instances of this class:
      One via the network initialization as part of the layer (for_custom == False)
      and another one via CustomLSTMFunctions (for_custom == True).
      The symbolic vars will look different. See self.create_vars_for_custom().
    """
    self.force_gpu = force_gpu
    if force_gpu:
      self.tt = cuda
    else:
      self.tt = T
    self.layer = layer
    self.input_vars = {}  # used as non_sequences for theano.scan(), i.e. as input for the step() function
    self.state_vars = {}  # updated in each step()
    self.state_vars_initial = {}
    self.custom_vars = {}
    self.for_custom = for_custom
    if for_custom:
      self.create_vars_for_custom()
    else:
      transforms_by_id[id(self)] = self
      self.create_vars()

  def copy_for_custom(self, force_gpu=True):
    """
    :returns a new instance of this class for LSTMCustomOp
    """
    return self.__class__(force_gpu=force_gpu, for_custom=True, layer=self.layer)

  def _create_var_for_custom(self, base_var):
    var = self._create_symbolic_var(base_var)
    setattr(self, var.name, var)
    return var

  def _create_symbolic_var(self, base_var):
    if self.force_gpu:
      base_type_class = cuda.CudaNdarrayType
    else:
      base_type_class = T.TensorType
    dtype = base_var.dtype
    ndim = base_var.ndim
    type_inst = base_type_class(dtype=dtype, broadcastable=(False,) * ndim)
    name = base_var.name
    var = type_inst(name)
    return var

  def create_vars_for_custom(self):
    """
    Called via CustomLSTMFunctions.
    """
    assert self.for_custom
    self.y_p = self.tt.fmatrix("y_p")

    layer_transform_instance = self.layer.recurrent_transform   # this is a different instance
    assert isinstance(layer_transform_instance, RecurrentTransformBase)
    assert layer_transform_instance.layer is self.layer
    for k, v in layer_transform_instance.custom_vars.items():
      assert getattr(layer_transform_instance, k) is v
      assert v.name == k
      self.custom_vars[k] = self._create_var_for_custom(v)
    self.state_vars_initial = None  # must not be used in custom op. we will get that from outside
    for k, v in layer_transform_instance.state_vars.items():
      assert getattr(layer_transform_instance, k) is v
      assert v.name == k
      self.state_vars[k] = self._create_var_for_custom(v)

  def init_vars(self):
    pass

  def create_vars(self):
    """
    Called for regular theano.scan().
    """
    pass

  def add_param(self, v, name = None):
    if name: v.name = name
    assert v.name
    if not self.for_custom:
      self.layer.add_param(v, v.name + "_" + self.name)
    self.add_var(v)
    return v

  def add_input(self, v, name=None):
    if name: v.name = name
    assert v.name
    self.input_vars[v.name] = v
    self.add_var(v)
    return v

  def add_state_var(self, initial_value, name=None):
    if name: initial_value.name = name
    assert initial_value.name
    sym_var = self._create_symbolic_var(initial_value)
    self.state_vars_initial[initial_value.name] = initial_value
    self.state_vars[initial_value.name] = sym_var
    return sym_var

  def add_var(self, v, name=None):
    if name: v.name = name
    assert v.name
    self.custom_vars[v.name] = v
    return v

  def get_sorted_non_sequence_inputs(self):
    return [v for (k, v) in sorted(self.input_vars.items())]

  def get_sorted_custom_vars(self):
    return [v for (k, v) in sorted(self.custom_vars.items())]

  def get_sorted_state_vars(self):
    return [v for (k, v) in sorted(self.state_vars.items())]

  def get_sorted_state_vars_initial(self):
    return [v for (k, v) in sorted(self.state_vars_initial.items())]

  def set_sorted_state_vars(self, state_vars):
    assert len(state_vars) == len(self.state_vars)
    for (k, v), v_new in zip(sorted(self.state_vars.items()), state_vars):
      assert getattr(self, k) is v
      assert v.name == k
      v_new.name = k
      self.state_vars[k] = v_new
      setattr(self, k, v_new)

  def get_state_vars_seq(self, state_var):
    assert state_var.name in self.state_vars
    idx = sorted(self.state_vars.keys()).index(state_var.name)
    return self.layer.recurrent_transform_state_var_seqs[idx]

  def step(self, y_p):
    """
    :param theano.Variable y_p: output of last time-frame. 2d (batch,dim)
    :return: z_re, updates
    :rtype: (theano.Variable, dict[theano.Variable, theano.Variable])
    """
    raise NotImplementedError

  def cost(self):
    """
    :rtype: theano.Variable | None
    """
    return None


class AttentionTest(RecurrentTransformBase):
  name = "test"

  def create_vars(self):
    n_out = self.layer.attrs['n_out']
    n_in = sum([e.attrs['n_out'] for e in self.layer.base])
    self.W_att_in = self.add_param(self.layer.create_random_uniform_weights(n=n_out, m=n_in, name="W_att_in"))

  def step(self, y_p):
    z_re = T.dot(y_p, self.W_att_in)
    return z_re, {}


class DummyTransform(RecurrentTransformBase):
  name = "none"
  def step(self, y_p):
    return T.zeros((y_p.shape[0],y_p.shape[1]*4),dtype='float32'), {}


class LM(RecurrentTransformBase):
  name = "none_lm"

  def create_vars(self):
    self.W_lm_in = self.add_var(self.layer.W_lm_in, name="W_lm_in")
    self.W_lm_out = self.add_var(self.layer.W_lm_out, name="W_lm_out")
    self.lmmask = self.add_var(self.layer.lmmask, "lmmask")
    self.t = self.add_state_var(T.zeros((self.layer.num_batches,), dtype="float32"), name="t")

  def step(self, y_p):
    #z_re += self.W_lm_out[T.argmax(T.dot(y_p,self.W_lm_in), axis=1)] * (T.ones_like(z_re) - self.lmmask[T.cast(self.t[0],'int32')])

    h_e = T.exp(T.dot(y_p, self.W_lm_in))
    #z_re = T.dot(h_e / (T.sum(h_e,axis=1,keepdims=True)), self.W_lm_out) * (T.ones_like(z_re) - self.lmmask[T.cast(self.t[0],'int32')])
    if self.layer.attrs['droplm'] < 1.0:
      z_re = self.W_lm_out[T.argmax(h_e / (T.sum(h_e,axis=1,keepdims=True)), axis=1)] * (1 - self.lmmask[T.cast(self.t[0],'int32')])
    else:
      z_re = self.W_lm_out[T.argmax(h_e / (T.sum(h_e,axis=1,keepdims=True)), axis=1)]

    return z_re, { self.t : self.t + 1 }


class NTM(RecurrentTransformBase):
  """
  Neural turing machine http://arxiv.org/pdf/1410.5401v2.pdf
  """
  name = 'ntm'

  class Head(object):
    def __init__(self, idx, parent, naddrs, ncells, max_shift):
      layer = parent.layer
      suffix = "_%s_%d"%(layer.name,idx)
      self.W_key = parent.add_param(layer.create_random_uniform_weights(n=naddrs,m=ncells, name="W_key"+suffix))
      self.b_key = parent.add_param(layer.create_bias(ncells, name="b_shift"+suffix))
      self.W_shift = parent.add_param(layer.create_random_uniform_weights(n=naddrs,m=max_shift, name="W_shift"+suffix))
      self.b_shift = parent.add_param(layer.create_bias(max_shift, name="b_shift"+suffix))
      self.W_beta = parent.add_param(layer.create_bias(naddrs, name="W_beta"+suffix))
      self.W_gamma = parent.add_param(layer.create_bias(naddrs, name="W_gamma"+suffix))
      self.W_g = parent.add_param(layer.create_bias(naddrs, name="W_g"+suffix))
      self.W_erase = parent.add_param(layer.create_random_uniform_weights(n=naddrs,m=ncells, name="W_erase"+suffix))
      self.b_erase = parent.add_param(layer.create_bias(ncells, name="b_erase"+suffix))
      self.W_add = parent.add_param(layer.create_random_uniform_weights(n=naddrs,m=ncells, name="W_add"+suffix))
      self.b_add = parent.add_param(layer.create_bias(ncells, name="b_add"+suffix))

    def softmax(self, x):
      ex = exp(x)
      return ex / sum(ex,axis=-1,keepdims=True)

    def step(self, y_p):
      key_t = T.dot(y_p, self.W_key) + self.b_key
      shift_t = self.softmax(T.dot(y_p, self.W_shift) + self.b_shift)
      beta_t = self.softmax(T.dot(y_p, self.W_beta))
      gamma_t = self.softmax(T.dot(y_p, self.W_beta)) + 1.0
      g_t = T.nnet.sigmoid(T.dot(y_p, self.W_g))
      erase_t = T.dot(y_p, self.W_erase) + self.b_erase
      add_t = T.dot(y_p, self.W_add) + self.b_add
      return key_t, beta_t, g_t, shift_t, gamma_t, erase_t, add_t


  def create_vars(self):
    import scipy
    layer = self.layer

    self.M = layer.add_state_var(T.zeros((layer.attrs['ntm_naddrs'], layer.attrs['ntm_ncells']), dtype='float32'), name='M')
    self.aw = self.add_state_var(T.zeros((layer.attrs['ntm_naddrs'],), dtype='float32'), name='aw')
    self.max_shift = self.add_var(theano.shared(numpy.cast['float32'](self.layer.attrs['ntm_shift']), name="max_shift"))
    self.naddrs = self.add_var(theano.shared(numpy.cast['float32'](self.layer.attrs['ntm_naddrs']), name="naddrs"))
    self.ncells = self.add_var(theano.shared(numpy.cast['float32'](self.layer.attrs['ntm_ncells']), name="ncells"))
    self.nheads = self.add_var(theano.shared(numpy.cast['float32'](self.layer.attrs['ntm_nheads']), name="nheads"))
    self.shift = self.add_input(theano.shared(
      value=scipy.linalg.circulant(numpy.arange(self.layer.attrs['ntm_naddrs'])).T[numpy.arange(-(self.layer.attrs['ntm_shift']//2),(self.layer.attrs['ntm_shift']//2)+1)][::-1],
      name='shift')) # no theano alternative available, this is from https://github.com/shawntan/neural-turing-machines/blob/master/model.py#L25

    self.heads = []
    for n in xrange(self.nheads):
      self.heads.append(Head(n,self,self.naddrs,self.ncells,self.max_shift))

    #for h in xrange(self.layer.attrs['ntm_nheads']):
    #  self.heads

  def step(self, y_p):



    return z_re, {}


class AttentionBase(RecurrentTransformBase):
  """
  Attention base class
  """

  def create_vars(self):
    layer = self.layer
    base = layer.base
    assert base, "attention networks are only defined for decoder networks"
    unit = layer.unit

    # if attention_step > 0:
    #   if attention_beam == 0:
    #     attention_beam = attention_step
    # elif attention_step == -1:
    #   assert attention_beam > 0
    #   self.index_range = T.arange(self.index.shape[0], dtype='float32').dimshuffle(0,'x','x').repeat(self.index.shape[1],axis=1)
    # else:
    #   assert attention_beam == 0

    # if self.attrs['attention'] != 'none' and attention_step != 0:
    #   outputs_info.append(T.alloc(numpy.cast['int32'](0), index.shape[1])) # focus (B)
    #   outputs_info.append(T.cast(T.alloc(numpy.cast['int32'](0), index.shape[1]) + attention_beam,'int32')) # beam (B)

    n_in = sum([e.attrs['n_out'] for e in base])
    src = [e.output for e in base]
    l = sqrt(6.) / sqrt(layer.attrs['n_out'] + n_in + unit.n_re)

    self.xb = layer.add_param(layer.create_bias(n_in, name='b_att'))
    #self.B = theano.gradient.disconnected_grad((T.concatenate(src, axis=2)) * base[0].index.dimshuffle(0,1,'x').repeat(n_in,axis=2)) + self.xb  # == B
    self.B = T.concatenate(src, axis=2) + self.xb  # == B
    self.B.name = "B"
    self.add_input(self.B)
    #if n_in != unit.n_out:
    #  values = numpy.asarray(self.rng.uniform(low=-l, high=l, size=(n_in, unit.n_units)), dtype=theano.config.floatX)
    #  self.W_att_proj = theano.shared(value=values, borrow=True, name = "W_att_proj")
    #  self.add_param(self.W_att_proj)
    #  self.xc = T.dot(self.xc, self.W_att_proj)
    #  n_in = unit.n_units
    values = numpy.asarray(layer.rng.uniform(low=-l, high=l, size=(layer.attrs['n_out'], n_in)), dtype=theano.config.floatX)
    self.W_att_re = self.add_param(theano.shared(value=values, borrow=True, name = "W_att_re"))
    values = numpy.asarray(layer.rng.uniform(low=-l, high=l, size=(n_in, layer.attrs['n_out'] * 4)), dtype=theano.config.floatX)
    self.W_att_in = self.add_param(theano.shared(value=values, borrow=True, name = "W_att_in"))


class AttentionDot(AttentionBase):
  """
  attention over dot product of base outputs and time dependent activation
  """
  name = "attention_dot"

  def create_vars(self):
    super(AttentionDot, self).create_vars()
    self.B = self.B - T.mean(self.B, axis=0, keepdims=True)
    self.B = self.B / T.sqrt(T.sum(T.sqr(self.B),axis=2,keepdims=True))
    self.add_input(self.B, 'B')
    #self.index = self.add_input(T.cast(self.layer.base[0].index, 'float32'), "index")

  def step(self, y_p):

    # #att_z = zc
    # att_x = xc  # == self.B
    # if attention_step != 0:
    #   focus_i = T.switch(T.ge(focus + beam,xc.shape[0]), xc.shape[0], focus + beam)
    #   focus_j = T.switch(T.lt(focus - beam,0), 0, focus - beam)
    #   focus_end = T.max(focus_i)
    #   focus_start = T.min(focus_j)
    #   #att_z = zc[focus_start:focus_end]
    #   att_x = xc[focus_start:focus_end]

    #f_z = T.sum(B * T.tanh(T.dot(y_p, W_att_quadr)).dimshuffle('x',0,1).repeat(B.shape[0],axis=0), axis=2, keepdims=True)
    y_f = T.tanh(T.dot(y_p, self.W_att_re))
    f_z = T.sum(self.B * (y_f / T.sqrt(T.sum(T.sqr(y_f),axis=1,keepdims=True))).dimshuffle('x',0,1).repeat(self.B.shape[0],axis=0), axis=2, keepdims=True)
    f_e = T.exp(f_z)
    w_t = f_e / T.sum(f_e, axis=0, keepdims=True) #- T.sum(T.ones_like(self.index)-self.index,axis=0,keepdims=True).dimshuffle(0,1,'x').repeat(f_e.shape[2],axis=2))

    import theano.printing
    #w_t = theano.printing.Print("w_t", attrs=['argmax(axis=0)'])(w_t)
    #w_t = theano.printing.Print("w_t",global_fn=print_wt)(w_t)
    z_re = T.dot(T.sum(self.B * w_t, axis=0, keepdims=False), self.W_att_in)

    # if attention_step == -1:
    #   #focus = focus_start + T.cast(T.mean(w_t,axis=0).flatten() * (focus_end - focus_start), 'int32')
    #   focus = T.cast(T.sum(w_t*self.index_range[focus_start:focus_end],axis=0).flatten() + 1,'int32') #T.cast(T.sum(T.arange(attention_beam, dtype='float32').dimshuffle(0,'x').repeat(w_t.shape[1],axis=1) * w_t, axis=0), 'int32')
    #   beam = T.cast(T.max([0.5 * T.exp(-T.sum(T.log(w_t)*w_t,axis=0)).flatten(),T.ones_like(beam)],axis=0),'int32') #T.cast(2.0 * T.max(-T.log(w_t),axis=0).flatten() * (focus_end - focus_start),'int32')
    #   result = [focus,beam] + result
    # elif attention_step > 0:
    #   result = [focus+attention_step,beam] + result

    return z_re, {}


class AttentionRBF(AttentionBase):
  """
  attention over rbf kernel of base outputs and time dependent activation
  """
  name = "attention_rbf"
  def create_vars(self):
    super(AttentionRBF, self).create_vars()
    self.B = self.B - T.mean(self.B, axis=0, keepdims=True)
    self.add_input(self.B, 'B')
    self.sigma = self.add_var(theano.shared(numpy.cast['float32'](self.layer.attrs['attention_sigma']), name="sigma"))
    self.index = self.add_input(T.cast(self.layer.base[0].index.dimshuffle(0,1,'x').repeat(self.B.shape[2],axis=2), 'float32'), 'index')

  def step(self, y_p):
    f_z = -T.sqrt(T.sum(T.sqr(self.B - T.tanh(T.dot(y_p, self.W_att_re)).dimshuffle('x',0,1).repeat(self.B.shape[0],axis=0)), axis=2, keepdims=True)) / self.sigma
    f_e = T.exp(f_z) #* self.index
    w_t = f_e / T.sum(f_e, axis=0, keepdims=True)
    return T.dot(T.sum(self.B * w_t, axis=0, keepdims=False), self.W_att_in), {}


class AttentionDotLM(AttentionDot):
  """
  attention over rbf kernel of base outputs and time dependent activation
  """
  name = "attention_dot_lm"
  def create_vars(self):
    super(AttentionDotLM, self).create_vars()
    self.W_lm_in = self.add_param(self.layer.W_lm_in, name = "W_lm_in")
    self.W_lm_out = self.add_param(self.layer.W_lm_out, name = "W_lm_out")
    self.lmmask = self.add_var(self.layer.lmmask,"lmmask")
    self.t = self.add_state_var(T.zeros((self.B.shape[1],), dtype="float32"), name="t")

  def step(self, y_p):
    z_re, updates = super(AttentionDotLM, self).step(y_p)

    #z_re += self.W_lm_out[T.argmax(T.dot(y_p,self.W_lm_in), axis=1)] * (T.ones_like(z_re) - self.lmmask[T.cast(self.t[0],'int32')])

    h_e = T.exp(T.dot(y_p, self.W_lm_in))
    #z_re += T.dot(h_e / (T.sum(h_e,axis=1,keepdims=True)), self.W_lm_out) * (T.ones_like(z_re) - self.lmmask[T.cast(self.t[0],'int32')])
    z_re += self.W_lm_out[T.argmax(h_e / (T.sum(h_e,axis=1,keepdims=True)), axis=1)] * (T.ones_like(z_re) - self.lmmask[T.cast(self.t[0],'int32')])

    updates[self.t] = self.t + T.ones_like(self.t)
    return z_re, updates


class AttentionRBFLM(AttentionRBF):
  """
  attention over rbf kernel of base outputs and time dependent activation
  """
  name = "attention_rbf_lm"
  def create_vars(self):
    super(AttentionRBFLM, self).create_vars()
    self.W_lm_in = self.add_param(self.layer.W_lm_in, name = "W_lm_in")
    self.W_lm_out = self.add_param(self.layer.W_lm_out, name = "W_lm_out")
    self.lmmask = self.add_var(self.layer.lmmask,"lmmask")
    self.t = self.add_state_var(T.zeros((self.B.shape[1],), dtype="float32"), name="t")

  def step(self, y_p):
    z_re, updates = super(AttentionRBFLM, self).step(y_p)

    #z_re += self.W_lm_out[T.argmax(T.dot(y_p,self.W_lm_in), axis=1)] * (T.ones_like(z_re) - self.lmmask[T.cast(self.t[0],'int32')])

    h_e = T.exp(T.dot(y_p, self.W_lm_in))
    #z_re += T.dot(h_e / (T.sum(h_e,axis=1,keepdims=True)), self.W_lm_out) * (T.ones_like(z_re) - self.lmmask[T.cast(self.t[0],'int32')])
    z_re += self.W_lm_out[T.argmax(h_e / (T.sum(h_e,axis=1,keepdims=True)), axis=1)] * (T.ones_like(z_re) - self.lmmask[T.cast(self.t[0],'int32')])

    updates[self.t] = self.t + T.ones_like(self.t)
    return z_re, updates


class AttentionBeam(AttentionBase):
  """
  beam attention over rbf kernel of base outputs and time dependent activation
  """
  name = "attention_beam"

  def create_vars_for_custom(self):
    super(AttentionBeam, self).create_vars_for_custom()
    self.beam = self.add_var(self.tt.fscalar('beam'))
    self.focus = self.add_state_var(theano.shared(value=numpy.zeros((50,), dtype="float32"), name="focus"))
    #self.focus = self.add_state_var(self.tt.fvector('focus'))
    self.index_range = self.add_var(self.tt.fmatrix('index_range'))
    self.loc = self.add_var(self.tt.fvector('loc')) # T.alloc(numpy.cast['int32'](0), 1)

  def create_vars(self):
    super(AttentionBeam, self).create_vars()
    self.beam = self.add_var(theano.shared(numpy.cast['float32'](self.layer.attrs['attention_beam']), name="beam"))
    self.focus = self.add_state_var(theano.shared(value=numpy.zeros((50,), dtype="float32"), name="focus"))  # (batch,)
    self.loc = T.alloc(numpy.cast['int32'](0), self.layer.index.shape[1])
    #self.focus = self.add_state_var(T.alloc(numpy.cast['float32'](0), self.layer.index.shape[1]), "focus")
    self.index_range = self.add_var(T.arange(self.layer.index.shape[0], dtype='float32').dimshuffle(0,'x').repeat(self.layer.index.shape[1],axis=1), "index_range")

  def step(self, y_p):
    import theano.printing
    focus = T.cast(self.focus, 'int32')
    beam = T.cast(self.beam, 'int32')
    #self.loc = theano.printing.Print("loc")(self.loc)
    self.loc += 1
    focus = T.cast(self.loc, 'int32')
    focus = theano.printing.Print("focus")(focus)
    focus_i = T.switch(T.ge(focus + beam,self.B.shape[0]), self.B.shape[0], focus + beam) #+ self.loc
    focus_j = T.switch(T.lt(focus - 1,0), 0, focus - 1)
    focus_i = theano.printing.Print("focus_start")(focus_i)
    focus_j = theano.printing.Print("focus_end")(focus_j)
    focus_end = T.max(focus_i) #theano.printing.Print("focus_end", T.max(focus_i))
    focus_start = T.min(focus_j)
    att_x = self.B[focus_start:focus_end]

    f_z = -T.sqrt(T.sum(T.sqr(att_x - T.tanh(T.dot(y_p, self.W_att_re)).dimshuffle('x',0,1).repeat(att_x.shape[0],axis=0)), axis=2, keepdims=True)) #/ self.sigma
    f_e = T.exp(f_z)
    w_t = f_e / T.sum(f_e, axis=0, keepdims=True)

    #focus = T.cast(T.argmax(w_t,axis=0).dimshuffle(0) + focus_start, 'float32') #T.sum(w_t[:,:,0]*self.index_range[focus_start:focus_end],axis=0)
    #focus = T.cast(T.argmax(w_t,axis=0).dimshuffle(0) + focus_start, 'float32') #T.sum(w_t[:,:,0]*self.index_range[focus_start:focus_end],axis=0)
    #focus = T.sum(w_t.dimshuffle(0,1)*T.arange(w_t.shape[0],dtype='float32').dimshuffle(0,'x').repeat(w_t.shape[1],axis=1),axis=0) #+ T.cast(focus_start,'float32') # #T.cast(T.sum(T.arange(attention_beam, dtype='float32').dimshuffle(0,'x').repeat(w_t.shape[1],axis=1) * w_t, axis=0), 'int32')
    self.loc += 3.0 * T.sum(w_t.dimshuffle(0,1)*T.arange(w_t.shape[0],dtype='float32').dimshuffle(0,'x').repeat(w_t.shape[1],axis=1),axis=0) / T.cast(w_t.shape[0],'float32')
    #focus = self.focus + 1
    #focus = self.focus + 1
    #self.focus += 1
    #self.focus = theano.printing.Print("focus")(self.focus)
    #w_t = theano.printing.Print("w_t",global_fn=print_wt)(w_t)

    #self.beam = T.cast(T.max([0.5 * T.exp(-T.sum(T.log(w_t)*w_t,axis=0)).flatten(),T.ones_like(beam)],axis=0),'int32') #T.cast(2.0 * T.max(-T.log(w_t),axis=0).flatten() * (focus_end - focus_start),'int32')

    return T.dot(T.sum(att_x * w_t, axis=0, keepdims=False), self.W_att_in), {} # self.focus : focus }


class AttentionTimeGauss(RecurrentTransformBase):
  name = "attention_time_gauss"

  def create_vars(self):
    layer = self.layer
    base = layer.base
    assert base, "attention networks are only defined for decoder networks"

    n_out = layer.attrs['n_out']
    n_in = sum([e.attrs['n_out'] for e in base])
    src = [e.output for e in base]

    self.B = T.concatenate(src, axis=2)  # base (output of encoder). (time,batch,encoder-dim)
    self.add_input(self.B, name="B")
    self.B_index = self.layer.base[0].index  # not an input
    self.B_times = self.add_input(T.cast(T.sum(self.B_index, axis=0), dtype="float32"), "B_times")  # float32 for gpu

    self.W_att_re = self.add_param(layer.create_random_uniform_weights(n=n_out, m=2, p=n_out, name="W_att_re"))
    self.b_att_re = self.add_param(layer.create_bias(2, name='b_att_re'))
    self.W_att_in = self.add_param(layer.create_random_uniform_weights(n=n_in, m=n_out * 4, name="W_att_in"))
    self.W_state_in = self.add_param(layer.create_random_uniform_weights(n=3, m=n_out * 4, name="W_state_in"))

    self.c = self.add_state_var(T.constant(0, dtype="float32"), name="c")  # float32 for gpu
    self.t = self.add_state_var(T.zeros((self.B.shape[1],), dtype="float32"), name="t")  # (batch,)

  def step(self, y_p):
    # y_p is (batch,n_out)
    # B is (time,batch,n_in)
    # B_index is (time,batch)
    attribs = self.layer.attrs["recurrent_transform_attribs"]
    n_batch = self.B.shape[1]
    dt_min = T.constant(attribs.get("dt_min", 0.5), dtype="float32")
    dt_max = T.constant(attribs.get("dt_max", 1.5), dtype="float32")
    std_min = T.constant(attribs.get("std_min", 1), dtype="float32")
    std_max = T.constant(attribs.get("std_max", 2), dtype="float32")
    n_beam = T.constant(attribs.get("beam", 20), dtype="float32")
    B_times = self.B_times

    b = self.b_att_re.dimshuffle('x', 0)  # (batch,2)
    a = T.nnet.sigmoid(T.dot(y_p, self.W_att_re) + b)  # (batch,2)
    dt = dt_min + a[:, 0] * (dt_max - dt_min)  # (batch,)
    std = std_min + a[:, 1] * (std_max - std_min)  # (batch,)
    std_t_bc = std.dimshuffle('x', 0)  # (beam,batch)

    t = self.t  # (batch,). that's the old t, which starts at zero.
    t_bc = t.dimshuffle('x', 0)  # (beam,batch)

    t_round = T.round(t)  # (batch,). +0.5 so that a later int-cast will be like round().
    start_idxs = t_round - n_beam / numpy.float32(2)  # (batch,), beams, centered around t_int
    idxs_0 = T.arange(n_beam).dimshuffle(0, 'x')  # (beam,batch). all on cpu, but static, no round trip
    idxs = T.cast(idxs_0, dtype="float32") + start_idxs.dimshuffle('x', 0)  # (beam,batch). centered around t_int

    # gauss window
    f_e = T.exp(-(T.cast(t_bc - idxs, dtype="float32") ** 2) / (2 * std_t_bc ** 2))  # (beam,batch)
    norm = T.constant(1.0, dtype="float32") / (std_t_bc * T.constant(sqrt(2 * pi), dtype="float32"))  # (beam,batch)
    w_t = f_e * norm  # (beam,batch)
    w_t_bc = w_t.dimshuffle(0, 1, 'x')  # (beam,batch,n_in)

    B_beam = multi_batch_beam(self.B, start_idxs, B_times, n_beam, "wrap_around")
    att = T.sum(B_beam * w_t_bc, axis=0, keepdims=False)  # (batch,n_in)
    z_re = T.dot(att, self.W_att_in)  # (batch,n_out*4)

    t_frac = T.cast((self.t + 1) / (self.c.dimshuffle('x') + 1), dtype="float32")  # (batch,)
    t_frac_row = t_frac.reshape((n_batch, 1))  # (batch,1)
    state_t_frac = T.constant(1, dtype="float32").dimshuffle('x', 'x') - t_frac_row  # (batch,1)
    state = T.concatenate([state_t_frac, a], axis=1)  # (batch,3)
    z_re += T.dot(state, self.W_state_in)

    return z_re, {self.t: self.t + dt, self.c: self.c + 1}

  def cost(self):
    t_seq = self.get_state_vars_seq(self.t)  # (time,batch)
    # Get the last frame. -2 because the last update is not used.
    B_index = self.B_index
    B_times = T.sum(B_index, axis=0)
    #B_times = T.printing.Print("B_times")(B_times)
    B_last = B_times - 1  # last frame idx of the base seq
    O_index = self.layer.index
    O_times = T.sum(O_index, axis=0)
    #O_times = T.printing.Print("O_times")(O_times)
    O_last = O_times - 2  # last frame. one less because initial states are in extra vector.
    # We need an extra check for small batches, would crash otherwise.
    O_last_clipped = T.clip(O_last, 0, t_seq.shape[0] - 1)
    batches = T.arange(t_seq.shape[1])  # (batch,)
    t_last = T.switch(T.lt(O_last, 0),
                      self.state_vars_initial["t"],
                      t_seq[O_last_clipped[batches], batches])  # (batch,)
    #t_last = T.printing.Print("t_last")(t_last)
    return T.sum((t_last - B_last) ** 2)


def get_dummy_recurrent_transform(recurrent_transform_name, n_out=5, n_batches=2, n_input_t=2, n_input_dim=2):
  """
  :type recurrent_transform_name: str
  :rtype: RecurrentTransformBase
  This function is a useful helper for testing/debugging.
  """
  cls = transform_classes[recurrent_transform_name]
  from NetworkRecurrentLayer import RecurrentUnitLayer
  from NetworkBaseLayer import SourceLayer
  if getattr(RecurrentUnitLayer, "rng", None) is None:
    RecurrentUnitLayer.initialize_rng()
  index = theano.shared(numpy.array([[1] * n_batches] * n_input_t, dtype="int8"), name="i")
  x_out = theano.shared(numpy.array([[[1.0] * n_input_dim] * n_batches] * n_input_t, dtype="float32"), name="x")
  layer = RecurrentUnitLayer(n_out=n_out, index=index, sources=[],
                             base=[SourceLayer(n_out=x_out.get_value().shape[2], x_out=x_out, index=index)],
                             attention=recurrent_transform_name)
  assert isinstance(layer.recurrent_transform, cls)
  return layer.recurrent_transform


transform_classes = {}; ":type: dict[str,class]"
transforms_by_id = {}; ":type: dict[int,RecurrentTransformBase]"

def _setup():
  import inspect
  for clazz in globals().values():
    if not inspect.isclass(clazz): continue
    if not issubclass(clazz, RecurrentTransformBase): continue
    if clazz.name is None: continue
    transform_classes[clazz.name] = clazz

_setup()