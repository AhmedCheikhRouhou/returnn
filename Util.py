
from __future__ import print_function

import subprocess
from subprocess import CalledProcessError
import h5py
from collections import deque
import inspect
import os
import sys
import shlex
import numpy as np
import re
import time
try:
  import thread
except ImportError:
  import _thread as thread
import threading

PY3 = sys.version_info[0] >= 3

if PY3:
  import builtins
  unicode = str
  long = int
else:
  import __builtin__ as builtins
  unicode = builtins.unicode
  long = builtins.long


class NotSpecified(object):
  """
  This is just a placeholder, to be used as default argument to mark that it is not specified.
  """


def is_64bit_platform():
  """
  :return: True if we run on 64bit, False for 32bit
  :rtype: bool
  http://stackoverflow.com/questions/1405913/how-do-i-determine-if-my-python-shell-is-executing-in-32bit-or-64bit-mode-on-os
  """
  return sys.maxsize > 2**32


class BackendEngine:
  Theano = 0
  Default = Theano
  TensorFlow = 1
  selectedEngine = None

  @classmethod
  def select_engine(cls, engine=None, config=None):
    """
    :param int engine:
    :param Config.Config config:
    """
    assert cls.selectedEngine is None, "already set"
    if engine is None:
      if config is None:
        from Config import get_global_config
        config = get_global_config()
      engine = cls.Default
      if config.bool("use_theano", False):
        engine = cls.Theano
      if config.bool("use_tensorflow", False):
        engine = cls.TensorFlow
    cls.selectedEngine = engine

  @classmethod
  def get_selected_engine(cls):
    if cls.selectedEngine is not None:
      return cls.selectedEngine
    else:
      return cls.Default

  @classmethod
  def is_theano_selected(cls):
    return cls.get_selected_engine() == cls.Theano

  @classmethod
  def is_tensorflow_selected(cls):
    return cls.get_selected_engine() == cls.TensorFlow


def cmd(s):
  """
  :type s: str
  :rtype: list[str]
  :returns all stdout splitted by newline. Does not cover stderr.
  Raises CalledProcessError on error.
  """
  p = subprocess.Popen(s, stdout=subprocess.PIPE, shell=True, close_fds=True,
                       env=dict(os.environ, LANG="en_US.UTF-8", LC_ALL="en_US.UTF-8"))
  stdout = p.communicate()[0]
  if PY3:
    stdout = stdout.decode("utf8")
  result = [tag.strip() for tag in stdout.split('\n')[:-1]]
  p.stdout.close()
  if p.returncode != 0:
    raise CalledProcessError(p.returncode, s, "\n".join(result))
  return result


def sysexecOut(*args, **kwargs):
  from subprocess import Popen, PIPE
  kwargs.setdefault("shell", False)
  p = Popen(args, stdin=PIPE, stdout=PIPE, **kwargs)
  out, _ = p.communicate()
  if p.returncode != 0: raise CalledProcessError(p.returncode, args)
  out = out.decode("utf-8")
  return out

def sysexecRetCode(*args, **kwargs):
  import subprocess
  res = subprocess.call(args, shell=False, **kwargs)
  valid = kwargs.get("valid", (0,1))
  if valid is not None:
    if res not in valid: raise CalledProcessError(res, args)
  return res

def git_commitRev(commit="HEAD", gitdir="."):
  if commit is None: commit = "HEAD"
  return sysexecOut("git", "rev-parse", "--short", commit, cwd=gitdir).strip()

def git_isDirty(gitdir="."):
  r = sysexecRetCode("git", "diff", "--no-ext-diff", "--quiet", "--exit-code", cwd=gitdir)
  if r == 0: return False
  if r == 1: return True
  assert False, "bad return %i" % r

def git_commitDate(commit="HEAD", gitdir="."):
  return sysexecOut("git", "show", "-s", "--format=%ci", commit, cwd=gitdir).strip()[:-6].replace(":", "").replace("-", "").replace(" ", ".")

def git_describeHeadVersion(gitdir="."):
  cdate = git_commitDate(gitdir=gitdir)
  rev = git_commitRev(gitdir=gitdir)
  is_dirty = git_isDirty(gitdir=gitdir)
  return "%s--git-%s%s" % (cdate, rev, "-dirty" if is_dirty else "")

def describe_crnn_version():
  mydir = os.path.dirname(__file__)
  try:
    return git_describeHeadVersion(gitdir=mydir)
  except Exception as e:
    return "unknown(git exception: %r)" % e

def describe_theano_version():
  import theano
  try:
    tdir = os.path.dirname(theano.__file__)
  except Exception as e:
    tdir = "<unknown(exception: %r)>" % e
  try:
    version = theano.__version__
    if len(version) > 20:
      version = version[:20] + "..."
  except Exception as e:
    version = "<unknown(exception: %r)>" % e
  try:
    if tdir.startswith("<"):
      git_info = "<unknown-dir>"
    elif os.path.exists(tdir + "/../.git"):
      git_info = "git:" + git_describeHeadVersion(gitdir=tdir)
    elif "/site-packages/" in tdir:
      git_info = "<site-package>"
    else:
      git_info = "<not-under-git>"
  except Exception as e:
    git_info = "<unknown(git exception: %r)>" % e
  return "%s (%s in %s)" % (version, git_info, tdir)

def describe_tensorflow_version():
  import tensorflow as tf
  try:
    tdir = os.path.dirname(tf.__file__)
  except Exception as e:
    tdir = "<unknown(exception: %r)>" % e
  version = getattr(tf, "__version__", "<unknown version>")
  version += " (%s)" % getattr(tf, "__git_version__", "<unknown git version>")
  try:
    if tdir.startswith("<"):
      git_info = "<unknown-dir>"
    elif os.path.exists(tdir + "/../.git"):
      git_info = "git:" + git_describeHeadVersion(gitdir=tdir)
    elif "/site-packages/" in tdir:
      git_info = "<site-package>"
    else:
      git_info = "<not-under-git>"
  except Exception as e:
    git_info = "<unknown(git exception: %r)>" % e
  return "%s (%s in %s)" % (version, git_info, tdir)

def get_tensorflow_version_tuple():
  """
  :return: tuple of ints, first entry is the major version
  :rtype: tuple[int]
  """
  import tensorflow as tf
  import re
  return tuple([int(re.sub('-rc[0-9]', '', s)) for s in tf.__version__.split(".")])

def eval_shell_env(token):
  if token.startswith("$"):
    return os.environ.get(token[1:], "")
  return token

def eval_shell_str(s):
  """
  :type s: str | list[str] | ()->str | list[()->str] | ()->list[str] | ()->list[()->str]
  :rtype: list[str]

  Parses `s` as shell like arguments (via shlex.split) and evaluates shell environment variables (eval_shell_env).
  `s` or its elements can also be callable. In those cases, they will be called and the returned value is used.
  """
  tokens = []
  if callable(s):
    s = s()
  if isinstance(s, (list, tuple)):
    l = s
  else:
    assert isinstance(s, (str, unicode))
    l = shlex.split(s)
  for token in l:
    if callable(token):
      token = token()
    assert isinstance(token, (str, unicode))
    if token.startswith("$"):
      tokens += eval_shell_str(eval_shell_env(token))
    else:
      tokens += [token]
  return tokens

def hdf5_dimension(filename, dimension):
  fin = h5py.File(filename, "r")
  if '/' in dimension:
    res = fin['/'.join(dimension.split('/')[:-1])].attrs[dimension.split('/')[-1]]
  else:
    res = fin.attrs[dimension]
  fin.close()
  return res

def hdf5_group(filename, dimension):
  fin = h5py.File(filename, "r")
  res = { k : fin[dimension].attrs[k] for k in fin[dimension].attrs }
  fin.close()
  return res

def hdf5_shape(filename, dimension):
  fin = h5py.File(filename, "r")
  res = fin[dimension].shape
  fin.close()
  return res

def hdf5_strings(handle, name, data):
  try:
    S=max([len(d) for d in data])
    dset = handle.create_dataset(name, (len(data),), dtype="S"+str(S))
    dset[...] = data
  except Exception:
    dt = h5py.special_dtype(vlen=unicode)
    del handle[name]
    dset = handle.create_dataset(name, (len(data),), dtype=dt)
    dset[...] = data

def model_epoch_from_filename(filename):
  if BackendEngine.is_theano_selected():
    return hdf5_dimension(filename, 'epoch')
  else:
    # We could check via:
    # tf.contrib.framework.python.framework.checkpoint_utils.load_variable()
    # once we save that in the model.
    # See TFNetwork.Network._create_saver().
    # For now, just parse it from filename.
    m = re.match(".*\.([0-9]+)", filename)
    assert m, "no match for %r" % filename
    return int(m.groups()[0])


def terminal_size(): # this will probably work on linux only
  import os, sys, io
  if not hasattr(sys.stdout, "fileno"):
    return -1, -1
  try:
    if not os.isatty(sys.stdout.fileno()):
      return -1, -1
  except io.UnsupportedOperation:
    return -1, -1
  env = os.environ
  def ioctl_GWINSZ(fd):
    try:
      import fcntl, termios, struct, os
      cr = struct.unpack('hh', fcntl.ioctl(fd, termios.TIOCGWINSZ,'1234'))
    except Exception:
        return
    return cr
  cr = ioctl_GWINSZ(0) or ioctl_GWINSZ(1) or ioctl_GWINSZ(2)
  if not cr:
    try:
        fd = os.open(os.ctermid(), os.O_RDONLY)
        cr = ioctl_GWINSZ(fd)
        os.close(fd)
    except Exception:
        pass
  if not cr:
    cr = (env.get('LINES', 25), env.get('COLUMNS', 80))
  return int(cr[1]), int(cr[0])


def hms(s):
  """
  :param float|int s: seconds
  :return: e.g. "1:23:45" (hs:ms:secs). see hms_fraction if you want to get fractional seconds
  :rtype: str
  """
  m, s = divmod(s, 60)
  h, m = divmod(m, 60)
  return "%d:%02d:%02d" % (h, m, s)


def hms_fraction(s, decimals=4):
  """
  :param float s: seconds
  :param int decimals: how much decimals to print
  :return: e.g. "1:23:45.6789" (hs:ms:secs)
  :rtype: str
  """
  return hms(int(s)) + (("%%.0%if" % decimals) % (s - int(s)))[1:]


def human_size(n, factor=1000, frac=0.8, prec=1):
  postfixs = ["", "K", "M", "G", "T"]
  i = 0
  while i < len(postfixs) - 1 and n > (factor ** (i + 1)) * frac:
    i += 1
  if i == 0:
    return str(n)
  return ("%." + str(prec) + "f") % (float(n) / (factor ** i)) + postfixs[i]


def progress_bar(complete = 1.0, prefix = "", suffix = ""):
  import sys
  terminal_width, _ = terminal_size()
  if terminal_width == -1: return
  if complete == 1.0:
    sys.stdout.write("\r%s"%(terminal_width * ' '))
    sys.stdout.flush()
    sys.stdout.write("\r")
    sys.stdout.flush()
    return
  progress = "%.02f%%" % (complete * 100)
  if prefix != "": prefix = prefix + " "
  if suffix != "": suffix = " " + suffix
  ntotal = terminal_width - len(progress) - len(prefix) - len(suffix) - 4
  bars = '|' * int(complete * ntotal)
  spaces = ' ' * (ntotal - int(complete * ntotal))
  bar = bars + spaces
  sys.stdout.write("\r%s" % prefix + "[" + bar[:len(bar)//2] + " " + progress + " " + bar[len(bar)//2:] + "]" + suffix)
  sys.stdout.flush()


class _progress_bar_with_time_stats:
  start_time = None
  last_complete = None

def progress_bar_with_time(complete=1.0, prefix="", **kwargs):
  stats = _progress_bar_with_time_stats
  if stats.start_time is None:
    stats.start_time = time.time()
    stats.last_complete = complete
  if stats.last_complete > complete:
    stats.start_time = time.time()
  stats.last_complete = complete

  start_elapsed = time.time() - stats.start_time
  if complete > 0:
    total_time_estimated = start_elapsed / complete
    remaining_estimated = total_time_estimated - start_elapsed
    if prefix:
      prefix += ", " + hms(remaining_estimated)
    else:
      prefix = hms(remaining_estimated)
  progress_bar(complete, prefix=prefix, **kwargs)


def availablePhysicalMemoryInBytes():
  try:
    mem_bytes = os.sysconf('SC_PAGE_SIZE') * os.sysconf('SC_PHYS_PAGES')
  except Exception:
    mem_bytes = 1024 ** 4  # just some random number, 1TB
  return mem_bytes

def defaultCacheSizeInGBytes(factor=0.7):
  mem_gbytes = availablePhysicalMemoryInBytes() / (1024. ** 3)
  return int(mem_gbytes * factor)


def betterRepr(o):
  """
  The main difference: this one is deterministic.
  The orig dict.__repr__ has the order undefined for dict or set.
  For big dicts/sets/lists, add "," at the end to make textual diffs nicer.
  """
  if isinstance(o, list):
    return "[\n%s]" % "".join(map(lambda v: betterRepr(v) + ",\n", o))
  if isinstance(o, deque):
    return "deque([\n%s])" % "".join(map(lambda v: betterRepr(v) + ",\n", o))
  if isinstance(o, tuple):
    if len(o) == 1:
      return "(%s,)" % o[0]
    return "(%s)" % ", ".join(map(betterRepr, o))
  if isinstance(o, dict):
    l = [betterRepr(k) + ": " + betterRepr(v) for (k,v) in sorted(o.items())]
    if sum([len(v) for v in l]) >= 40:
      return "{\n%s}" % "".join([v + ",\n" for v in l])
    else:
      return "{%s}" % ", ".join(l)
  if isinstance(o, set):
    return "set([\n%s])" % "".join(map(lambda v: betterRepr(v) + ",\n", o))
  # fallback
  return repr(o)


def simpleObjRepr(obj):
  """
  All self.__init__ args.
  """
  return obj.__class__.__name__ + "(%s)" % \
                                  ", ".join(["%s=%s" % (arg, betterRepr(getattr(obj, arg)))
                                             for arg in inspect.getargspec(obj.__init__).args[1:]])


class ObjAsDict:
  def __init__(self, obj):
    self.__obj = obj

  def __getitem__(self, item):
    if not isinstance(item, (str, unicode)):
      raise KeyError(item)
    try:
      return getattr(self.__obj, item)
    except AttributeError as e:
      raise KeyError(e)

  def items(self):
    return vars(self.__obj).items()


class DictAsObj:
  def __init__(self, dikt):
    self.__dict__ = dikt


def dict_joined(*ds):
  res = {}
  for d in ds:
    res.update(d)
  return res


def obj_diff_str(self, other):
  if self is None and other is None:
    return "No diff."
  if self is None and other is not None:
    return "self is None and other is %r" % other
  if self is not None and other is None:
    return "other is None and self is %r" % self
  if self == other:
    return "No diff."
  s = []
  def _obj_attribs(obj):
    d = getattr(obj, "__dict__", None)
    if d is not None:
      return d.keys()
    return None
  self_attribs = _obj_attribs(self)
  other_attribs = _obj_attribs(other)
  if self_attribs is None or other_attribs is None:
    return "self: %r, other: %r" % (self, other)
  for attrib in sorted(set(self_attribs).union(other_attribs)):
    if attrib not in self_attribs or attrib not in other_attribs:
      s += ["attrib %r not on both" % attrib]
      continue
    value_self = getattr(self, attrib)
    value_other = getattr(other, attrib)
    if isinstance(value_self, list):
      if not isinstance(value_other, list):
        s += ["attrib %r self is list but other is %r" % (attrib, type(value_other))]
      elif len(value_self) != len(value_other):
        s += ["attrib %r list differ. len self: %i, len other: %i" % (attrib, len(value_self), len(value_other))]
      else:
        for i, (a, b) in enumerate(zip(value_self, value_other)):
          if a != b:
            s += ["attrib %r[%i] differ. self: %r, other: %r" % (attrib, i, a, b)]
    elif isinstance(value_self, dict):
      if not isinstance(value_other, dict):
        s += ["attrib %r self is dict but other is %r" % (attrib, type(value_other))]
      elif value_self != value_other:
        s += ["attrib %r dict differs:" % attrib]
        s += ["  " + l for l in dict_diff_str(value_self, value_other).splitlines()]
    else:
      if value_self != value_other:
        s += ["attrib %r differ. self: %r, other: %r" % (attrib, value_self, value_other)]
  if s:
    return "\n".join(s)
  else:
    return "No diff."


def dict_diff_str(self, other):
  return obj_diff_str(DictAsObj(self), DictAsObj(other))


def find_ranges(l):
  """
  :type l: list[int]
  :returns list of ranges (start,end) where end is exclusive
  such that the union of range(start,end) matches l.
  :rtype: list[(int,int)]
  We expect that the incoming list is sorted and strongly monotonic increasing.
  """
  if not l:
    return []
  ranges = [(l[0], l[0])]
  for k in l:
    assert k >= ranges[-1][1]  # strongly monotonic increasing
    if k == ranges[-1][1]:
      ranges[-1] = (ranges[-1][0], k + 1)
    else:
      ranges += [(k, k + 1)]
  return ranges


def initThreadJoinHack():
  if PY3:
    # Not sure if needed, but also, the code below is slightly broken.
    return
  mainThread = threading.currentThread()
  assert isinstance(mainThread, threading._MainThread)
  mainThreadId = thread.get_ident()

  # Patch Thread.join().
  join_orig = threading.Thread.join
  def join_hacked(threadObj, timeout=None):
    """
    :type threadObj: threading.Thread
    :type timeout: float|None
    """
    if timeout is None and thread.get_ident() == mainThreadId:
      # This is a HACK for Thread.join() if we are in the main thread.
      # In that case, a Thread.join(timeout=None) would hang and even not respond to signals
      # because signals will get delivered to other threads and Python would forward
      # them for delayed handling to the main thread which hangs.
      # See CPython signalmodule.c.
      # Currently the best solution I can think of:
      while threadObj.isAlive():
        join_orig(threadObj, timeout=0.1)
    else:
      # In all other cases, we can use the original.
      join_orig(threadObj, timeout=timeout)
  threading.Thread.join = join_hacked

  # Mostly the same for Condition.wait().
  cond_wait_orig = threading._Condition.wait
  def cond_wait_hacked(cond, timeout=None, *args):
    if timeout is None and thread.get_ident() == mainThreadId:
      # Use a timeout anyway. This should not matter for the underlying code.
      cond_wait_orig(cond, timeout=0.1)
    else:
      cond_wait_orig(cond, timeout=timeout)
  threading._Condition.wait = cond_wait_hacked


def start_daemon_thread(target, args=()):
  from threading import Thread
  t = Thread(target=target, args=args)
  t.daemon = True
  t.start()

def is_quitting():
  import rnn
  if rnn.quit:  # via rnn.finalize()
    return True
  if getattr(sys, "exited", False):  # set via Debug module when an unexpected SIGINT occurs, or here
    return True
  return False

def interrupt_main():
  is_main_thread = isinstance(threading.currentThread(), threading._MainThread)
  if is_quitting():  # ignore if we are already quitting
    if is_main_thread:  # strange to get again in main thread
      raise Exception("interrupt_main() from main thread while already quitting")
    # Not main thread. This will just exit the thread.
    sys.exit(1)
  sys.exited = True  # Don't do it twice.
  sys.exited_frame = sys._getframe()
  if is_main_thread:
    raise KeyboardInterrupt
  else:
    thread.interrupt_main()
    sys.exit(1)  # And exit the thread.


class AsyncThreadRun(threading.Thread):
  def __init__(self, name, func):
    """
    :param str name:
    :param ()->T func:
    """
    super(AsyncThreadRun, self).__init__(name=name, target=self.main)
    self.func = func
    self.result = None
    self.daemon = True
    self.start()

  def main(self):
    self.result = wrap_async_func(self.func)

  def get(self):
    self.join()
    return self.result


def wrap_async_func(f):
  try:
    import better_exchook
    better_exchook.install()
    return f()
  except Exception:
    sys.excepthook(*sys.exc_info())
    interrupt_main()


def try_run(func, args=(), catch_exc=Exception, default=None):
  try:
    return func(*args)
  except catch_exc:
    return default


def class_idx_seq_to_1_of_k(seq, num_classes):
  num_frames = len(seq)
  m = np.zeros((num_frames, num_classes))
  m[np.arange(num_frames), seq] = 1
  return m


def uniq(seq):
  """
  Like Unix tool uniq. Removes repeated entries.
  :param seq: numpy.array
  :return: seq
  """
  diffs = np.ones_like(seq)
  diffs[1:] = seq[1:] - seq[:-1]
  idx = diffs.nonzero()
  return seq[idx]


def slice_pad_zeros(x, begin, end, axis=0):
  """
  :param numpy.ndarray x: of shape (..., time, ...)
  :param int begin:
  :param int end:
  :param int axis:
  :return: basically x[begin:end] (with axis==0) but if begin < 0 or end > x.shape[0],
   it will not discard these frames but pad zeros, such that the resulting shape[0] == end - begin.
  :rtype: numpy.ndarray
  """
  assert axis == 0, "not yet fully implemented otherwise"
  pad_left, pad_right = 0, 0
  if begin < 0:
    pad_left = -begin
    begin = 0
  elif begin >= x.shape[axis]:
    return np.zeros((end - begin,) + x.shape[1:], dtype=x.dtype)
  assert end >= begin
  if end > x.shape[axis]:
    pad_right = end - x.shape[axis]
    end = x.shape[axis]
  return np.pad(x[begin:end], [(pad_left, pad_right)] + [(0, 0)] * (x.ndim - 1), mode="constant")


def random_orthogonal(shape, gain=1., seed=None):
  """
  Returns a random orthogonal matrix of the given shape.
  Code borrowed and adapted from Keras: https://github.com/fchollet/keras/blob/master/keras/initializers.py
  Reference: Saxe et al., http://arxiv.org/abs/1312.6120
  Related: Unitary Evolution Recurrent Neural Networks, https://arxiv.org/abs/1511.06464

  :param tuple[int] shape:
  :param float gain:
  :param int seed: for Numpy random generator
  :return: random orthogonal matrix
  :rtype: numpy.ndarray
  """
  num_rows = 1
  for dim in shape[:-1]:
    num_rows *= dim
  num_cols = shape[-1]
  flat_shape = (num_rows, num_cols)
  if seed is not None:
    rnd = np.random.RandomState(seed=seed)
  else:
    rnd = np.random
  a = rnd.normal(0.0, 1.0, flat_shape)
  u, _, v = np.linalg.svd(a, full_matrices=False)
  # Pick the one with the correct shape.
  q = u if u.shape == flat_shape else v
  q = q.reshape(shape)
  return gain * q[:shape[0], :shape[1]]


_have_inplace_increment = None
_native_inplace_increment = None

def inplace_increment(x, idx, y):
  """
  This basically does `x[idx] += y`.
  The difference to the Numpy version is that in case some index is there multiple
  times, it will only be incremented once (and it is not specified which one).
  See also theano.tensor.subtensor.AdvancedIncSubtensor documentation.
  """
  global _have_inplace_increment, inplace_increment, _native_inplace_increment
  if _have_inplace_increment is None:
    native_inpl_incr = None
    import theano
    if theano.config.cxx:
      import theano.gof.cutils  # needed to import cutils_ext
      try:
        from cutils_ext.cutils_ext import inplace_increment as native_inpl_incr
      except ImportError:
        pass
    if native_inpl_incr:
      _have_inplace_increment = True
      _native_inplace_increment = native_inpl_incr
      inplace_increment = native_inpl_incr  # replace myself
      return inplace_increment(x, idx, y)
    _have_inplace_increment = False
  if _have_inplace_increment is True:
    return _native_inplace_increment(x, idx, y)
  raise NotImplementedError("need Numpy 1.8 or later")



def parse_orthography_into_symbols(orthography, upper_case_special=True, word_based=False):
  """
  For Speech.
  Example:
    orthography = "hello [HESITATION] there "
    with word_based == False: returns list("hello ") + ["[HESITATION]"] + list(" there ").
    with word_based == True: returns ["hello", "[HESITATION]", "there"]
  No pre/post-processing such as:
  Spaces are kept as-is. No stripping at begin/end. (E.g. trailing spaces are not removed.)
  No tolower/toupper.
  Doesn't add [BEGIN]/[END] symbols or so.
  Any such operations should be done explicitly in an additional function.
  Anything in []-brackets are meant as special-symbols.
  Also see parse_orthography() which includes some preprocessing.

  :param str orthography: example: "hello [HESITATION] there "
  :param bool upper_case_special: whether the special symbols are always made upper case
  :param bool word_based: whether we split on space and return full words
  :rtype: list[str]
  """
  ret = []
  in_special = 0
  for c in orthography:
    if in_special:
      if c == "[":  # special-special
        in_special += 1
        ret[-1] += "["
      elif c == "]":
        in_special -= 1
        ret[-1] += "]"
      elif upper_case_special:
        ret[-1] += c.upper()
      else:
        ret[-1] += c
    else:  # not in_special
      if c == "[":
        in_special = 1
        ret += ["["]
      else:
        if word_based:
          if c.isspace():
            ret += [""]
          else:
            if not ret:
              ret += [""]
            ret[-1] += c
        else:  # not word_based
          ret += c
  return ret


def parse_orthography(orthography, prefix=(), postfix=("[END]",),
                      remove_chars="(){}", collapse_spaces=True, final_strip=True,
                      **kwargs):
  """
  For Speech. Full processing.
  Example:
    orthography = "hello [HESITATION] there "
    with word_based == False: returns list("hello ") + ["[HESITATION]"] + list(" there") + ["[END]"]
    with word_based == True: returns ["hello", "[HESITATION]", "there", "[END]"]
  Does some preprocessing on orthography and then passes it on to parse_orthography_into_symbols().

  :param str orthography: e.g. "hello [HESITATION] there "
  :param list[str] prefix: will add this prefix
  :param list[str] postfix: will add this postfix
  :param str remove_chars: those chars will just be removed at the beginning
  :param bool collapse_spaces: whether multiple spaces and tabs are collapsed into a single space
  :param bool final_strip: whether we strip left and right
  :param **kwargs: passed on to parse_orthography_into_symbols()
  :rtype: list[str]
  """
  for c in remove_chars:
    orthography = orthography.replace(c, "")
  if collapse_spaces:
    orthography = " ".join(orthography.split())
  if final_strip:
    orthography = orthography.strip()
  return list(prefix) + parse_orthography_into_symbols(orthography, **kwargs) + list(postfix)


def json_remove_comments(string, strip_space=True):
  """
  :type string: str
  :rtype: str

  via https://github.com/getify/JSON.minify/blob/master/minify_json.py,
  by Gerald Storer, Pradyun S. Gedam, modified by us.
  """
  tokenizer = re.compile('"|(/\*)|(\*/)|(//)|\n|\r')
  end_slashes_re = re.compile(r'(\\)*$')

  in_string = False
  in_multi = False
  in_single = False

  new_str = []
  index = 0

  for match in re.finditer(tokenizer, string):

    if not (in_multi or in_single):
      tmp = string[index:match.start()]
      if not in_string and strip_space:
        # replace white space as defined in standard
        tmp = re.sub('[ \t\n\r]+', '', tmp)
      new_str.append(tmp)

    index = match.end()
    val = match.group()

    if val == '"' and not (in_multi or in_single):
      escaped = end_slashes_re.search(string, 0, match.start())

      # start of string or unescaped quote character to end string
      if not in_string or (escaped is None or len(escaped.group()) % 2 == 0):
        in_string = not in_string
      index -= 1 # include " character in next catch
    elif not (in_string or in_multi or in_single):
      if val == '/*':
        in_multi = True
      elif val == '//':
        in_single = True
    elif val == '*/' and in_multi and not (in_string or in_single):
      in_multi = False
    elif val in '\r\n' and not (in_multi or in_string) and in_single:
      in_single = False
    elif not ((in_multi or in_single) or (val in ' \r\n\t' and strip_space)):
      new_str.append(val)

  new_str.append(string[index:])
  return ''.join(new_str)


def unicode_to_str_recursive(s):
  if isinstance(s, dict):
    return {unicode_to_str_recursive(key): unicode_to_str_recursive(value) for key, value in s.items()}
  elif isinstance(s, list):
    return [unicode_to_str_recursive(element) for element in s]
  elif isinstance(s, unicode):
    return s.encode('utf-8')
  else:
    return s


def load_json(filename=None, content=None):
  if content:
    assert not filename
  else:
    content = open(filename).read()
  import json
  content = json_remove_comments(content)
  try:
    json_content = json.loads(content)
  except ValueError as e:
    raise Exception("config looks like JSON but invalid json content, %r" % e)
  if not PY3:
    json_content = unicode_to_str_recursive(json_content)
  return json_content


class NumbersDict:
  """
  It's mostly like dict[str,float|int] & some optional broadcast default value.
  It implements the standard math bin ops in a straight-forward way.
  """

  def __init__(self, auto_convert=None, numbers_dict=None, broadcast_value=None):
    if auto_convert is not None:
      assert broadcast_value is None
      assert numbers_dict is None
      if isinstance(auto_convert, dict):
        numbers_dict = auto_convert
      elif isinstance(auto_convert, NumbersDict):
        numbers_dict = auto_convert.dict
        broadcast_value = auto_convert.value
      else:
        broadcast_value = auto_convert
    if numbers_dict is None:
      numbers_dict = {}
    else:
      numbers_dict = dict(numbers_dict)  # force copy

    self.dict = numbers_dict
    self.value = broadcast_value
    self.max = self.__max_error

  def copy(self):
    return NumbersDict(self)

  def constant_like(self, number):
    return NumbersDict(
      broadcast_value=number if (self.value is not None) else None,
      numbers_dict={k: number for k in self.dict.keys()})

  @property
  def keys_set(self):
    return set(self.dict.keys())

  def __getitem__(self, key):
    if self.value is not None:
      return self.dict.get(key, self.value)
    return self.dict[key]

  def __setitem__(self, key, value):
    self.dict[key] = value

  def __delitem__(self, key):
    del self.dict[key]

  def get(self, key, default=None):
    # Keep consistent with self.__get_item__. If self.value is set, this will always be the default value.
    return self.dict.get(key, self.value if self.value is not None else default)

  def pop(self, key, *args):
    return self.dict.pop(key, *args)

  def __iter__(self):
    # This can potentially cause confusion. So enforce explicitness.
    # For a dict, we would return the dict keys here.
    # Also, max(self) would result in a call to self.__iter__(),
    # which would only make sense for our values, not the dict keys.
    raise Exception("%s.__iter__ is undefined" % self.__class__.__name__)

  def keys(self):
    return self.dict.keys()

  def values(self):
    return list(self.dict.values()) + ([self.value] if self.value is not None else [])

  def has_values(self):
    return bool(self.dict) or self.value is not None

  def unary_op(self, op):
    res = NumbersDict()
    if self.value is not None:
      res.value = op(self.value)
    for k, v in self.dict.items():
      res.dict[k] = op(v)
    return res

  @classmethod
  def bin_op_scalar_optional(cls, self, other, zero, op):
    if self is None and other is None:
      return None
    if self is None:
      self = zero
    if other is None:
      other = zero
    return op(self, other)

  @classmethod
  def bin_op(cls, self, other, op, zero, result=None):
    if not isinstance(self, NumbersDict):
      if isinstance(other, NumbersDict):
        self = other.constant_like(self)
      else:
        self = NumbersDict(self)
    if not isinstance(other, NumbersDict):
      other = self.constant_like(other)
    if result is None:
      result = NumbersDict()
    assert isinstance(result, NumbersDict)
    for k in self.keys_set | other.keys_set:
      result[k] = cls.bin_op_scalar_optional(self.get(k, None), other.get(k, None), zero=zero, op=op)
    result.value = cls.bin_op_scalar_optional(self.value, other.value, zero=zero, op=op)
    return result

  def __add__(self, other):
    return self.bin_op(self, other, op=lambda a, b: a + b, zero=0)

  __radd__ = __add__

  def __iadd__(self, other):
    return self.bin_op(self, other, op=lambda a, b: a + b, zero=0, result=self)

  def __sub__(self, other):
    return self.bin_op(self, other, op=lambda a, b: a - b, zero=0)

  def __rsub__(self, other):
    return self.bin_op(self, other, op=lambda a, b: b - a, zero=0)

  def __isub__(self, other):
    return self.bin_op(self, other, op=lambda a, b: a - b, zero=0, result=self)

  def __mul__(self, other):
    return self.bin_op(self, other, op=lambda a, b: a * b, zero=1)

  __rmul__ = __mul__

  def __imul__(self, other):
    return self.bin_op(self, other, op=lambda a, b: a * b, zero=1, result=self)

  def __div__(self, other):
    return self.bin_op(self, other, op=lambda a, b: a / b, zero=1)

  __rdiv__ = __div__
  __truediv__ = __div__

  def __idiv__(self, other):
    return self.bin_op(self, other, op=lambda a, b: a / b, zero=1, result=self)

  __itruediv__ = __idiv__

  def __floordiv__(self, other):
    return self.bin_op(self, other, op=lambda a, b: a // b, zero=1)

  def __ifloordiv__(self, other):
    return self.bin_op(self, other, op=lambda a, b: a // b, zero=1, result=self)

  def __neg__(self):
    return self.unary_op(op=lambda a: -a)

  def __bool__(self):
    return any(self.values())

  __nonzero__ = __bool__  # Python 2

  def elem_eq(self, other, result_with_default=True):
    """
    Element-wise equality check with other.
    Note about broadcast default value: Consider some key which is neither in self nor in other.
      This means that self[key] == self.default, other[key] == other.default.
      Thus, in case that self.default != other.default, we get res.default == False.
      Then, all(res.values()) == False, even when all other values are True.
      This is sometimes not what we want.
      You can control the behavior via result_with_default.
    """
    def op(a, b):
      if a is None:
        return None
      if b is None:
        return None
      return a == b
    res = self.bin_op(self, other, op=op, zero=None)
    if not result_with_default:
      res.value = None
    return res

  def __eq__(self, other):
    return all(self.elem_eq(other).values())

  def __ne__(self, other):
    return not (self == other)

  def __cmp__(self, other):
    # There is no good straight-forward implementation
    # and it would just confuse.
    raise Exception("%s.__cmp__ is undefined" % self.__class__.__name__)

  @staticmethod
  def _max(*args):
    args = [a for a in args if a is not None]
    if not args:
      return None
    if len(args) == 1:
      return args[0]
    return max(*args)

  @staticmethod
  def _min(*args):
    args = [a for a in args if a is not None]
    if not args:
      return None
    if len(args) == 1:
      return args[0]
    return min(*args)

  @classmethod
  def max(cls, items):
    """
    Element-wise maximum for item in items.
    :param list[NumbersDict|int|float] items:
    :rtype: NumbersDict
    """
    assert items
    if len(items) == 1:
      return NumbersDict(items[0])
    if len(items) == 2:
      return cls.bin_op(items[0], items[1], op=cls._max, zero=None)
    return cls.max([items[0], cls.max(items[1:])])

  @classmethod
  def min(cls, items):
    """
    Element-wise minimum for item in items.
    :param list[NumbersDict|int|float] items:
    :rtype: NumbersDict
    """
    assert items
    if len(items) == 1:
      return NumbersDict(items[0])
    if len(items) == 2:
      return cls.bin_op(items[0], items[1], op=cls._min, zero=None)
    return cls.min([items[0], cls.min(items[1:])])

  @staticmethod
  def __max_error():
    # Will replace self.max for each instance. To be sure that we don't confuse it with self.max_value.
    raise Exception("Use max_value instead.")

  def max_value(self):
    """
    Maximum of our values.
    """
    return max(self.values())

  def __repr__(self):
    if self.value is None and not self.dict:
      return "%s()" % self.__class__.__name__
    if self.value is None and self.dict:
      return "%s(%r)" % (self.__class__.__name__, self.dict)
    if not self.dict and self.value is not None:
      return "%s(%r)" % (self.__class__.__name__, self.value)
    return "%s(numbers_dict=%r, broadcast_value=%r)" % (
           self.__class__.__name__, self.dict, self.value)


def collect_class_init_kwargs(cls, only_with_default=False):
  """
  :param type cls: class, where it assumes that kwargs are passed on to base classes
  :param bool only_with_default: if given will only return the kwargs with default values
  :return: set if not with_default, otherwise the dict to the default values
  :rtype: list[str] | dict[str]
  """
  from collections import OrderedDict
  if only_with_default:
    kwargs = OrderedDict()
  else:
    kwargs = []
  if PY3:
    getargspec = inspect.getfullargspec
  else:
    getargspec = inspect.getargspec
  for cls_ in inspect.getmro(cls):
    # Check Python function. Could be builtin func or so. Python 2 getargspec does not work in that case.
    if not inspect.ismethod(cls_.__init__) and not inspect.isfunction(cls_.__init__):
      continue
    arg_spec = getargspec(cls_.__init__)
    args = arg_spec.args[1:]  # first arg is self, ignore
    if only_with_default:
      if arg_spec.defaults:
        assert len(arg_spec.defaults) <= len(args)
        args = args[len(args) - len(arg_spec.defaults):]
        assert len(arg_spec.defaults) == len(args), arg_spec
        for arg, default in zip(args, arg_spec.defaults):
          kwargs[arg] = default
    else:
      for arg in args:
        if arg not in kwargs:
          kwargs.append(arg)
  return kwargs


def collect_mandatory_class_init_kwargs(cls):
  """
  :param type cls:
  :return: list of kwargs which have no default, i.e. which must be provided
  :rtype: list[str]
  """
  all_kwargs = collect_class_init_kwargs(cls, only_with_default=False)
  default_kwargs = collect_class_init_kwargs(cls, only_with_default=True)
  mandatory_kwargs = []
  for arg in all_kwargs:
    if arg not in default_kwargs:
      mandatory_kwargs.append(arg)
  return mandatory_kwargs


def help_on_type_error_wrong_args(cls, kwargs):
  """
  :param type cls:
  :param list[str] kwargs:
  """
  mandatory_args = collect_mandatory_class_init_kwargs(cls)
  for arg in kwargs:
    if arg in mandatory_args:
      mandatory_args.remove(arg)
  all_kwargs = collect_class_init_kwargs(cls)
  unknown_args = []
  for arg in kwargs:
    if arg not in all_kwargs:
      unknown_args.append(arg)
  if mandatory_args or unknown_args:
    print("Args mismatch? Missing are %r, unknowns are %r." % (mandatory_args, unknown_args))


def custom_exec(source, source_filename, user_ns, user_global_ns):
  if not source.endswith("\n"):
    source += "\n"
  co = compile(source, source_filename, "exec")
  user_global_ns["__package__"] = __package__  # important so that imports work when CRNN itself is loaded as a package
  eval(co, user_global_ns, user_ns)


class FrozenDict(dict):
  def __setitem__(self, key, value):
    raise ValueError("FrozenDict cannot be modified")

  def __hash__(self):
    return hash(tuple(sorted(self.items())))


def make_hashable(obj):
  """
  Theano needs hashable objects in some cases, e.g. the properties of Ops.
  This converts all objects as such, i.e. into immutable frozen types.
  """
  if isinstance(obj, dict):
    return FrozenDict([make_hashable(item) for item in obj.items()])
  elif isinstance(obj, (list, tuple)):
    return tuple([make_hashable(item) for item in obj])
  elif isinstance(obj, (str, unicode, float, int, long)):
    return obj
  elif obj is None:
    return obj
  else:
    assert False, "don't know how to make hashable: %r (%r)" % (obj, type(obj))


def make_dll_name(basename):
  if sys.platform == "darwin":
    return "lib%s.dylib" % basename
  elif sys.platform == "win32":
    return "%s.dll" % basename
  else:  # Linux, Unix
    return "lib%s.so" % basename


def escape_c_str(s):
  return '"%s"' % s.replace("\\\\", "\\").replace("\n", "\\n").replace("\"", "\\\"").replace("'", "\\'")


def attr_chain(base, attribs):
  if not isinstance(attribs, (list, tuple)):
    assert isinstance(attribs, str)
    attribs = [attribs]
  else:
    attribs = list(attribs)
  for i in range(len(attribs)):
    base = getattr(base, attribs[i])
  return base


def to_bool(v):
  try:
    return bool(int(v))
  except ValueError:
    pass
  if isinstance(v, (str, unicode)):
    v = v.lower()
    if v in ["true", "yes", "on", "1"]: return True
    if v in ["false", "no", "off", "0"]: return False
  raise ValueError("to_bool cannot handle %r" % v)


def as_str(s):
  if isinstance(s, str):
    return s
  if isinstance(s, bytes):
    return s.decode("utf8")
  assert False, "unknown type %s" % type(s)


def load_txt_vector(filename):
  """
  Expect line-based text encoding in file.
  We also support Sprint XML format, which has some additional xml header and footer,
  which we will just strip away.

  :param str filename:
  :rtype: list[float]
  """
  return [float(l) for l in open(filename).read().splitlines() if l and not l.startswith("<")]


class CollectionReadCheckCovered:
  def __init__(self, collection):
    self.collection = collection
    self.got_items = set()

  def __getitem__(self, item):
    res = self.collection[item]
    self.got_items.add(item)
    return res

  def get(self, item, default=None):
    try:
      return self[item]
    except KeyError:
      return default

  def __len__(self):
    return len(self.collection)

  def __iter__(self):
    for k in self.collection:
      yield self[k]

  def assert_all_read(self):
    remaining = set(self.collection).difference(self.got_items)
    assert not remaining, "The keys %r were not read in the collection %r." % (remaining, self.collection)


def which(program):
  def is_exe(fpath):
    return os.path.isfile(fpath) and os.access(fpath, os.X_OK)

  fpath, fname = os.path.split(program)
  if fpath:
    if is_exe(program):
      return program
  else:
    for path in os.environ["PATH"].split(os.pathsep):
      path = path.strip('"')
      exe_file = os.path.join(path, program)
      if is_exe(exe_file):
        return exe_file

  return None

_original_execv = None
_original_execve = None
_original_execvpe = None

def overwrite_os_exec(prefix_args):
  """
  :param list[str] prefix_args:
  """
  global _original_execv, _original_execve, _original_execvpe
  if not _original_execv:
    _original_execv = os.execv
  if not _original_execve:
    _original_execve = os.execve
  if not _original_execvpe:
    _original_execvpe = os._execvpe

  def wrapped_execvpe(file, args, env=None):
    new_args = prefix_args + [which(args[0])] + args[1:]
    sys.stderr.write("$ %s\n" % " ".join(new_args))
    sys.stderr.flush()
    _original_execvpe(file=prefix_args[0], args=new_args, env=env)

  def execv(path, args):
    if args[:len(prefix_args)] == prefix_args:
      _original_execv(path, args)
    else:
      wrapped_execvpe(path, args)

  def execve(path, args, env):
    if args[:len(prefix_args)] == prefix_args:
      _original_execve(path, args, env)
    else:
      wrapped_execvpe(path, args, env)

  def execl(file, *args):
    """execl(file, *args)

    Execute the executable file with argument list args, replacing the
    current process. """
    os.execv(file, args)

  def execle(file, *args):
    """execle(file, *args, env)

    Execute the executable file with argument list args and
    environment env, replacing the current process. """
    env = args[-1]
    os.execve(file, args[:-1], env)

  def execlp(file, *args):
    """execlp(file, *args)

    Execute the executable file (which is searched for along $PATH)
    with argument list args, replacing the current process. """
    os.execvp(file, args)

  def execlpe(file, *args):
    """execlpe(file, *args, env)

    Execute the executable file (which is searched for along $PATH)
    with argument list args and environment env, replacing the current
    process. """
    env = args[-1]
    os.execvpe(file, args[:-1], env)

  def execvp(file, args):
    """execvp(file, args)

    Execute the executable file (which is searched for along $PATH)
    with argument list args, replacing the current process.
    args may be a list or tuple of strings. """
    wrapped_execvpe(file, args)

  def execvpe(file, args, env):
    """execvpe(file, args, env)

    Execute the executable file (which is searched for along $PATH)
    with argument list args and environment env , replacing the
    current process.
    args may be a list or tuple of strings. """
    wrapped_execvpe(file, args, env)

  os.execv = execv
  os.execve = execve
  os.execl = execl
  os.execle = execle
  os.execlp = execlp
  os.execlpe = execlpe
  os.execvp = execvp
  os.execvpe = execvpe
  os._execvpe = wrapped_execvpe


def get_lsb_release():
  d = {}
  for l in open("/etc/lsb-release").read().splitlines():
    k, v = l.split("=", 1)
    if v[0] == v[-1] == "\"":
      v = v[1:-1]
    d[k] = v
  return d


def get_ubuntu_major_version():
  """
  :rtype: int|None
  """
  d = get_lsb_release()
  if d["DISTRIB_ID"] != "Ubuntu":
    return None
  return int(float(d["DISTRIB_RELEASE"]))


def auto_prefix_os_exec_prefix_ubuntu(prefix_args, ubuntu_min_version=16):
  """
  :param list[str] prefix_args:
  :param int ubuntu_min_version:

  Example usage:
    auto_prefix_os_exec_prefix_ubuntu(["/u/zeyer/tools/glibc217/ld-linux-x86-64.so.2"])
  """
  ubuntu_version = get_ubuntu_major_version()
  if ubuntu_version is None:
    return
  if ubuntu_version >= ubuntu_min_version:
    return
  print("You are running Ubuntu %i, thus we prefix all os.exec with %s." % (ubuntu_version, prefix_args))
  assert os.path.exists(prefix_args[0])
  overwrite_os_exec(prefix_args=prefix_args)


def cleanup_env_var_path(env_var, path_prefix):
  """
  :param str env_var: e.g. "LD_LIBRARY_PATH"
  :param str path_prefix:

  Will remove all paths in os.environ[env_var] which are prefixed with path_prefix.
  """
  if env_var not in os.environ:
    return
  ps = os.environ[env_var].split(":")
  def f(p):
    if p == path_prefix or p.startswith(path_prefix + "/"):
      print("Removing %s from %s." % (p, env_var))
      return False
    return True
  ps = filter(f, ps)
  os.environ[env_var] = ":".join(ps)


def get_login_username():
  """
  :rtype: str
  :return: the username of the current user.
  Use this as a replacement for os.getlogin().
  """
  import os
  if sys.platform == 'win32':
    return os.getlogin()
  import pwd
  return pwd.getpwuid(os.getuid())[0]


def get_temp_dir():
  """
  :rtype: str
  :return: e.g. "/tmp/$USERNAME"
  """
  username = get_login_username()
  for envname in ['TMPDIR', 'TEMP', 'TMP']:
    dirname = os.getenv(envname)
    if dirname:
      return "%s/%s" % (dirname, username)
  return "/tmp/%s" % username


class LockFile(object):
  def __init__(self, directory, name="lock_file", lock_timeout=1 * 60 * 60):
    """
    :param str directory:
    :param int|float lock_timeout: in seconds
    """
    self.directory = directory
    self.name = name
    self.fd = None
    self.lock_timeout = lock_timeout
    self.lockfile = "%s/%s" % (directory, name)

  def is_old_lockfile(self):
    try:
      mtime = os.path.getmtime(self.lockfile)
    except OSError:
      mtime = None
    if mtime and (abs(time.time() - mtime) > self.lock_timeout):
      return True
    return False

  def maybe_remove_old_lockfile(self):
    if not self.is_old_lockfile():
      return
    print("Removing old lockfile %r (probably crashed proc)." % self.lockfile)
    try:
      os.remove(self.lockfile)
    except OSError as exc:
      print("Remove lockfile exception %r. Ignoring it." % exc)

  def is_locked(self):
    if self.is_old_lockfile():
      return False
    try:
      return os.path.exists(self.lockfile)
    except OSError:
      return False

  def lock(self):
    import time
    import errno
    while True:
      # Try to create directory if it does not exist.
      try:
        os.makedirs(self.directory)
      except OSError:
        pass  # Ignore any errors.
      # Now try to create the lock.
      try:
        self.fd = os.open(self.lockfile, os.O_CREAT | os.O_EXCL | os.O_RDWR)
        return
      except OSError as exc:
        # Possible errors:
        # ENOENT (No such file or directory), e.g. if the directory was deleted.
        # EEXIST (File exists), if the lock already exists.
        if exc.errno not in [errno.ENOENT, errno.EEXIST]:
          raise  # Other error, so reraise.
      # We did not get the lock.
      # Check if it is a really old one.
      self.maybe_remove_old_lockfile()
      # Wait a bit, and then retry.
      time.sleep(1)

  def unlock(self):
    os.close(self.fd)
    os.remove(self.lockfile)

  def __enter__(self):
    self.lock()

  def __exit__(self, exc_type, exc_val, exc_tb):
    self.unlock()


def str_is_number(s):
  """
  :param str s: e.g. "1", ".3" or "x"
  :return: whether s can be casted to float or int
  :rtype: bool
  """
  try:
    float(s)
    return True
  except ValueError:
    return False


def sorted_values_from_dict(d):
  assert isinstance(d, dict)
  return [v for (k, v) in sorted(d.items())]


def dict_zip(keys, values):
  assert len(keys) == len(values)
  return dict(zip(keys, values))


def parse_ld_conf_file(fn):
  """
  Via https://github.com/albertz/system-tools/blob/master/bin/find-lib-in-path.py.
  :param str fn: e.g. "/etc/ld.so.conf"
  :return: list of paths for libs
  :rtype: list[str]
  """
  from glob import glob
  paths = []
  for l in open(fn).read().splitlines():
    l = l.strip()
    if not l:
      continue
    if l.startswith("#"):
      continue
    if l.startswith("include "):
      for sub_fn in glob(l[len("include "):]):
        paths.extend(parse_ld_conf_file(sub_fn))
      continue
    paths.append(l)
  return paths


def get_ld_paths():
  """
  To be very correct, see man-page of ld.so.
  And here: http://unix.stackexchange.com/questions/354295/what-is-the-default-value-of-ld-library-path/354296
  Short version, not specific to an executable, in this order:
  - LD_LIBRARY_PATH
  - /etc/ld.so.cache (instead we will parse /etc/ld.so.conf)
  - /lib, /usr/lib (or maybe /lib64, /usr/lib64)
  Via https://github.com/albertz/system-tools/blob/master/bin/find-lib-in-path.py.

  :rtype: list[str]
  :return: list of paths to search for libs (*.so files)
  """
  paths = []
  if "LD_LIBRARY_PATH" in os.environ:
    paths.extend(os.environ["LD_LIBRARY_PATH"].split(":"))
  if os.path.exists("/etc/ld.so.conf"):
    paths.extend(parse_ld_conf_file("/etc/ld.so.conf"))
  paths.extend(["/lib", "/usr/lib", "/lib64", "/usr/lib64"])
  return paths


def find_lib(lib_name):
  """
  :param str lib_name: without postfix/prefix, e.g. "cudart" or "blas"
  :return: returns full path to lib or None
  :rtype: str|None
  """
  if sys.platform == "darwin":
    prefix = "lib"
    postfix = ".dylib"
  elif sys.platform == "win32":
    prefix = ""
    postfix = ".dll"
  else:
    prefix = "lib"
    postfix = ".so"
  for path in get_ld_paths():
    fn = "%s/%s%s%s" % (path, prefix, lib_name, postfix)
    if os.path.exists(fn):
      return fn
  return None


def read_sge_num_procs(job_id=None):
  """
  From the Sun Grid Engine (SGE), reads the num_proc setting for a particular job.
  If job_id is not provided and the JOB_ID env is set, it will use that instead (i.e. it uses the current job).
  This calls qstat to figure out this setting. There are multiple ways this can go wrong,
  so better catch any exception.

  :param int|None job_id:
  :return: num_proc
  :rtype: int|None
  """
  if not job_id:
    if not os.environ.get("SGE_ROOT"):
      return None
    try:
      job_id = int(os.environ.get("JOB_ID") or 0)
    except ValueError as exc:
      raise Exception("read_sge_num_procs: %r, invalid JOB_ID: %r" % (exc, os.environ.get("JOB_ID")))
    if not job_id:
      return None
  from subprocess import Popen, PIPE, CalledProcessError
  cmd = ["qstat", "-j", str(job_id)]
  proc = Popen(cmd, stdout=PIPE)
  stdout, _ = proc.communicate()
  if proc.returncode:
    raise CalledProcessError(proc.returncode, cmd, stdout)
  stdout = stdout.decode("utf8")
  ls = [l[len("hard resource_list:"):].strip() for l in stdout.splitlines() if l.startswith("hard resource_list:")]
  assert len(ls) == 1
  opts = dict([opt.split("=", 1) for opt in ls[0].split(",")])
  try:
    return int(opts["num_proc"])
  except ValueError as exc:
    raise Exception("read_sge_num_procs: %r, invalid num_proc %r for job id %i.\nline: %r" % (
      exc, opts["num_proc"], job_id, ls[0]))


def try_and_ignore_exception(f):
  try:
    f()
  except Exception as exc:
    print("try_and_ignore_exception: %r failed: %s" % (f, exc))
    sys.excepthook(*sys.exc_info())


def try_get_caller_name(depth=1, fallback=None):
  """
  :param int depth:
  :param str|None fallback: this is returned if we fail for some reason
  :rtype: str|None
  :return: caller function name. this is just for debugging
  """
  try:
    frame = sys._getframe(depth + 1)  # one more to count ourselves
    return frame.f_code.co_name
  except Exception:
    return fallback


def camel_case_to_snake_case(name):
  """
  :param str name: e.g. "CamelCase"
  :return: e.g. "camel_case"
  :rtype: str
  """
  s1 = re.sub('(.)([A-Z][a-z]+)', r'\1_\2', name)
  return re.sub('([a-z0-9])([A-Z])', r'\1_\2', s1).lower()
