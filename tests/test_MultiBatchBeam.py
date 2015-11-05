
import numpy
from nose.tools import assert_equal, assert_is
import MultiBatchBeam
from MultiBatchBeam import *
import better_exchook
better_exchook.replace_traceback_format_tb()


naive_multi_batch_beam = MultiBatchBeam._naive_multi_batch_beam

def numpy_multi_batch_beam(array, start_idxs, batch_lens, beam_width, wrap_mode, pad_left=0, pad_right=0, idx_dim=0, batch_dim=1):
  array = T.as_tensor(array)
  start_idxs = T.as_tensor(start_idxs)
  batch_lens = T.as_tensor(batch_lens)
  beam_width = T.as_tensor(beam_width)
  op = MultiBatchBeamOp(wrap_mode, idx_dim, batch_dim)
  beam = op(array, start_idxs, batch_lens, beam_width, pad_left, pad_right)
  return beam.eval()

def theano_cpu_multi_batch_beam(*args, **kwargs):
  res = MultiBatchBeam._theano_cpu_multi_batch_beam(*args, **kwargs)
  return res.eval()

naive_multi_batch_beam_grad = MultiBatchBeam._naive_multi_batch_beam_grad

def _eval_or_None(x):
  if isinstance(x.type, T.DisconnectedType):
    return None
  return x.eval()

def theano_op_multi_batch_beam_grad(array, start_idxs, batch_lens, beam_width, wrap_mode, pad_left=0, pad_right=0, idx_dim=0, batch_dim=1, output_grad=None):
  array = T.as_tensor(array)
  start_idxs = T.as_tensor(start_idxs)
  batch_lens = T.as_tensor(batch_lens)
  beam_width = T.as_tensor(beam_width)
  pad_left = T.as_tensor(pad_left)
  pad_right = T.as_tensor(pad_right)
  output_grad = T.as_tensor(output_grad)
  op = MultiBatchBeamOp(wrap_mode, idx_dim, batch_dim)
  D_array, D_start_idxs, D_batch_lens, D_beam_width, D_pad_left, D_pad_right = op.grad((array, start_idxs, batch_lens, beam_width, pad_left, pad_right), (output_grad, ))
  return map(_eval_or_None, [D_array, D_pad_left, D_pad_right])

def theano_cpu_multi_batch_beam_grad(array, start_idxs, batch_lens, beam_width, wrap_mode, pad_left=0, pad_right=0, idx_dim=0, batch_dim=1, output_grad=None):
  array = T.as_tensor(array)
  start_idxs = T.as_tensor(start_idxs)
  batch_lens = T.as_tensor(batch_lens)
  beam_width = T.as_tensor(beam_width)
  pad_left = T.as_tensor(pad_left)
  pad_right = T.as_tensor(pad_right)
  output_grad = T.as_tensor(output_grad)
  res = MultiBatchBeam._theano_cpu_multi_batch_beam(array, start_idxs, batch_lens, beam_width, wrap_mode, pad_left, pad_right, idx_dim, batch_dim)
  D_array, D_pad_left, D_pad_right = T.grad(None, wrt=[array, pad_left, pad_right], known_grads={res: output_grad}, disconnected_inputs="ignore", return_disconnected="Disconnected")
  return map(_eval_or_None, [D_array, D_pad_left, D_pad_right])


def compare_implementations(*args, **kwargs):
  results = {}
  for method in ["numpy", "naive", "theano_cpu"]:
    m = globals()["%s_multi_batch_beam" % method]
    try:
      res = m(*args, **kwargs)
    except NotImplementedError:
      pass
    else:
      results[method] = res
  assert len(results) > 1
  for k, v in sorted(results.items()):
    print "fwd %s:" % k
    print v
  reference = sorted(results.keys())[0]
  for k in sorted(results.keys())[1:]:
    assert_equal(results[k].shape, results[reference].shape)
    numpy.testing.assert_almost_equal(results[k], results[reference])
  return results[reference]


def compare_grad_implementations(*args, **kwargs):
  results = {}
  for method in ["theano_op", "naive", "theano_cpu"]:
    m = globals()["%s_multi_batch_beam_grad" % method]
    try:
      res = m(*args, **kwargs)
    except NotImplementedError:
      pass
    else:
      results[method] = res
  assert len(results) > 1
  for k, v in sorted(results.items()):
    print "bwd %s:" % k
    print v
  reference = sorted(results.keys())[0]
  for k in sorted(results.keys())[1:]:
    assert_equal(len(results[k]), len(results[reference]))
    for i in range(len(results[k])):
      if results[k][i] is None or results[reference][i] is None:
        assert_is(results[k][i], results[reference][i])
        continue
      assert_equal(results[k][i].shape, results[reference][i].shape)
      # The summation of the grad can be quite numerically unstable, thus the low decimal.
      numpy.testing.assert_almost_equal(results[k][i], results[reference][i], decimal=4)
  return results[reference]


def test_numpy_perform_simple():
  n_time = 5
  n_batch = 1
  n_dim = 1
  array = numpy.arange(n_time * n_batch * n_dim).reshape(n_time, n_batch, n_dim)
  start_idxs = numpy.array([0])
  batch_lens = numpy.array([n_time])
  beam_width = n_time
  beam = compare_implementations(array, start_idxs, batch_lens, beam_width, "wrap_around")
  numpy.testing.assert_almost_equal(beam, array)


def test_numpy_perform_simple_1a():
  n_time = 5
  n_batch = 2
  array = numpy.arange(n_time * n_batch).reshape(n_time, n_batch)
  start_idxs = numpy.array([0, 0])
  batch_lens = numpy.array([n_time, n_time])
  beam_width = n_time
  beam = compare_implementations(array, start_idxs, batch_lens, beam_width, "wrap_around")
  numpy.testing.assert_almost_equal(beam, array)


def test_numpy_perform_simple_1():
  n_time = 5
  n_batch = 2
  n_dim = 1
  array = numpy.arange(n_time * n_batch * n_dim).reshape(n_time, n_batch, n_dim)
  start_idxs = numpy.array([0, 0])
  batch_lens = numpy.array([n_time, n_time])
  beam_width = n_time
  beam = compare_implementations(array, start_idxs, batch_lens, beam_width, "wrap_around")
  numpy.testing.assert_almost_equal(beam, array)


def test_numpy_perform_simple_2():
  n_time = 5
  n_batch = 2
  n_dim = 2
  array = numpy.arange(n_time * n_batch * n_dim).reshape(n_time, n_batch, n_dim)
  start_idxs = numpy.array([0, 0])
  batch_lens = numpy.array([n_time, n_time])
  beam_width = n_time
  beam = compare_implementations(array, start_idxs, batch_lens, beam_width, "wrap_around")
  numpy.testing.assert_almost_equal(beam, array)


def test_numpy_perform_1():
  n_time = 11
  n_batch = 5
  n_dim = 3
  array = numpy.array([42,43,44] + range(n_time * n_batch * n_dim)[:-3]).reshape(n_time, n_batch, n_dim) + 0.1
  print "array shape:", array.shape
  start_idxs = numpy.array([1, -2, 10, 0, 1])
  batch_lens = numpy.array([11, 2, 11, 2, 11])
  beam_width = 5
  compare_implementations(array, start_idxs, batch_lens, beam_width, "wrap_around")


def test_numpy_perform_2_wrap():
  array = numpy.array([range(10)]).T
  start_idxs = numpy.array([-2])
  batch_lens = numpy.array([array.shape[0]])
  beam_width = 4
  beam = compare_implementations(array, start_idxs, batch_lens, beam_width, "wrap_around")
  assert beam.shape == (4, 1)
  assert_equal(list(beam[:, 0]), [8, 9, 0, 1])


def test_grad_simple():
  array = numpy.array([range(10)], dtype="float32").T
  n_batch = array.shape[1]
  assert n_batch == 1
  start_idxs = numpy.array([-2])
  batch_lens = numpy.array([array.shape[0]])
  beam_width = 4
  D_beam = numpy.arange(4, dtype="float32").reshape(beam_width, n_batch)
  D_array, _, _ = compare_grad_implementations(array, start_idxs, batch_lens, beam_width, "wrap_around", output_grad=D_beam)
  assert D_array.shape == array.shape
  assert_equal(list(D_array[:, 0]), [2, 3] + [0] * 6 + [0, 1])


def test_random_wrap():
  n_time = 100
  n_batch = 10
  n_dim = 5
  beam_width = 20
  numpy.random.seed(123)
  array = numpy.random.random(n_time * n_batch * n_dim).reshape(n_time, n_batch, n_dim)
  batch_lens = numpy.array([numpy.random.randint(n_time / 5, n_time) for i in range(n_batch)])
  start_idxs = numpy.array([numpy.random.randint(-n_time, n_time) for i in range(n_batch)])
  beam = compare_implementations(array, start_idxs, batch_lens, beam_width, "wrap_around")
  D_beam = numpy.random.random(beam.shape)
  compare_grad_implementations(array, start_idxs, batch_lens, beam_width, "wrap_around", output_grad=D_beam)

def test_random_pad():
  n_time = 100
  n_batch = 10
  n_dim = 5
  beam_width = 20
  wrap_mode = "pad"
  pad_left = 42
  pad_right = -17
  numpy.random.seed(123)
  array = numpy.random.random(n_time * n_batch * n_dim).reshape(n_time, n_batch, n_dim)
  batch_lens = numpy.array([numpy.random.randint(n_time / 5, n_time) for i in range(n_batch)])
  start_idxs = numpy.array([numpy.random.randint(-n_time, n_time) for i in range(n_batch)])
  beam = compare_implementations(array, start_idxs, batch_lens, beam_width, wrap_mode, pad_left, pad_right)
  D_beam = numpy.random.random(beam.shape)
  compare_grad_implementations(array, start_idxs, batch_lens, beam_width, wrap_mode, pad_left, pad_right, output_grad=D_beam)

def test_inc_subtensor():
  # If there are some indexes multiple times in the subtensor,
  # we expect for inc_subtensor that they are all accumulated.
  a = T.inc_subtensor(T.arange(10)[[0, 3, 5, 0]], numpy.array([-1,-2,-3,-4])).eval()
  assert_equal(list(a), [-5,  1,  2,  1,  4,  2,  6,  7,  8,  9])
