from collections import Counter, defaultdict, namedtuple, Sequence, Iterator
from itertools import count

from pddlstream.conversion import list_from_conjunction, substitute_expression, get_args, is_parameter
from pddlstream.downward import parse_lisp
from pddlstream.function import Result, Instance, External, ExternalInfo, parse_function, \
    parse_predicate, DEBUG
from pddlstream.object import Object, OptimisticObject
from pddlstream.utils import str_from_tuple, INF
import time

class BoundedGenerator(Iterator):
    def __init__(self, generator, max_calls=INF):
        self.generator = generator
        self.max_calls = max_calls
        self.calls = 0
    @property
    def enumerated(self):
        return self.max_calls <= self.calls
    def next(self):
        if self.enumerated:
            raise StopIteration()
        self.calls += 1
        return next(self.generator)
    __next__ = next

##################################################

def from_list_gen_fn(list_gen_fn):
    return list_gen_fn
    #return lambda *args: ListGenerator(list_gen_fn(*args))


def from_gen_fn(gen_fn):
    return from_list_gen_fn(lambda *args: ([] if output_values is None else [output_values]
                                           for output_values in gen_fn(*args)))

##################################################

def from_list_fn(list_fn):
    #return lambda *args: iter([list_fn(*args)])
    return lambda *args: BoundedGenerator(iter([list_fn(*args)]), max_calls=1)


def from_fn(fn):
    def list_fn(*args):
        outputs = fn(*args)
        return [] if outputs is None else [outputs]
    return from_list_fn(list_fn)


def from_test(test):
    return from_fn(lambda *args: tuple() if test(*args) else None)

#def list_gen_from_constant(constant):
#    return from_fn(lambda *args: constant)
#
def fn_from_constant(constant):
    return lambda *args: constant

def empty_gen():
    return lambda *args: iter([])

##################################################

def get_empty_fn():
    return lambda *input_values: None

def get_constant_fn(constant):
    return lambda *input_values: constant

def get_identity_fn(indices):
    return lambda *input_values: tuple(input_values[i] for i in indices)

##################################################

#UniqueOpt = namedtuple('UniqueOpt', ['instance', 'output_index'])
SharedOpt = namedtuple('SharedOpt', ['external', 'output_index'])

def get_shared_gen_fn(stream): # TODO: identify bound
    def gen_fn(*input_values):
        output_values = tuple(SharedOpt(stream, i) for i in range(len(stream.outputs)))
        yield [output_values]
    return gen_fn

# def create_partial_fn():
#     # TODO: indices or names
#     raise NotImplementedError()
#     #return get_partial_fn

def get_constant_gen_fn(stream, constant):
    def gen_fn(*input_values):
        assert(len(stream.inputs) == len(input_values))
        output_values = tuple(constant for _ in range(len(stream.outputs)))
        yield [output_values]
    return gen_fn

# def get_unique_fn(stream):
#     # TODO: this should take into account the output number...
#     def fn(*input_values):
#         #input_objects = map(opt_obj_from_value, input_values)
#         #stream_instance = stream.get_instance(input_objects)
#         #output_values = tuple(UniqueOpt(stream_instance, i) for i in range(len(stream.outputs)))
#         output_values = tuple(object() for _ in range(len(stream.outputs)))
#         return [output_values]
#     return fn

class DebugValue(object): # TODO: could just do an object
    _output_counts = defaultdict(count)
    def __init__(self, stream, input_values, output_parameter):
        self.stream = stream
        self.input_values = input_values
        self.output_parameter = output_parameter
        self.index = next(self._output_counts[output_parameter])
    def __repr__(self):
        return '${}{}'.format(self.output_parameter[1:], self.index)

##################################################

class StreamInfo(ExternalInfo):
    def __init__(self, opt_gen_fn=None, eager=False,
                 p_success=None, overhead=None):
        # TODO: could change frequency/priority for the incremental algorithm
        super(StreamInfo, self).__init__(eager, p_success, overhead)
        self.opt_gen_fn = opt_gen_fn
        #self.order = 0

##################################################

class StreamResult(Result):
    def __init__(self, instance, output_objects, opt_index=None):
        super(StreamResult, self).__init__(instance, opt_index)
        self.output_objects = tuple(output_objects)
        self.mapping = dict(zip(self.instance.external.outputs, self.output_objects))
        self.mapping.update(instance.mapping)
        self.certified = substitute_expression(self.instance.external.certified, self.get_mapping())
    def get_mapping(self):
        return self.mapping
    def get_certified(self):
        return self.certified
    def get_tuple(self):
        name = self.instance.external.name
        return name, self.instance.input_objects, self.output_objects
    def __repr__(self):
        return '{}:{}->{}'.format(self.instance.external.name,
                                  str_from_tuple(self.instance.input_objects),
                                  str_from_tuple(self.output_objects))

class StreamInstance(Instance):
    def __init__(self, stream, input_objects):
        super(StreamInstance, self).__init__(stream, input_objects)
        self._generator = None
        self.opt_index = stream.num_opt_fns
    def _check_output_values(self, new_values):
        if not isinstance(new_values, Sequence):
            raise ValueError('An output list for stream [{}] is not a sequence: {}'.format(self.external.name, new_values))
        for output_values in new_values:
            if not isinstance(output_values, Sequence):
                raise ValueError('An output tuple for stream [{}] is not a sequence: {}'.format(
                    self.external.name, output_values))
            if len(output_values) != len(self.external.outputs):
                raise ValueError('An output tuple for stream [{}] has length {} instead of {}: {}'.format(
                    self.external.name, len(output_values), len(self.external.outputs), output_values))
    def _next_outputs(self):
        if self._generator is None:
            self._generator = self.external.gen_fn(*self.get_input_values())
        new_values = []
        try:
            new_values = next(self._generator)
        except StopIteration:
            self.enumerated = True
        if isinstance(self._generator, BoundedGenerator):
            self.enumerated = self._generator.enumerated
        return new_values
    def next_results(self, verbose=False):
        start_time = time.time()
        assert not self.enumerated
        new_values = self._next_outputs()
        if verbose:
            print('{}:{}->[{}]'.format(self.external.name, str_from_tuple(self.get_input_values()),
                                       ', '.join(map(str_from_tuple, new_values))))
        self._check_output_values(new_values)
        results = []
        for output_values in new_values:
            output_objects = tuple(map(Object.from_value, output_values))
            results.append(self.external._Result(self, output_objects))
        self.update_statistics(start_time, results)
        return results
    def next_optimistic(self):
        if self.enumerated or self.disabled:
            return []
        # TODO: (potentially infinite) sequence of optimistic objects
        # TODO: how do I distinguish between real not real verifications of things?
        new_values = []
        for output_list in self.external.opt_gen_fn(*self.get_input_values()):
            new_values.extend(output_list)
        self._check_output_values(new_values)
        results = []
        for i, output_values in enumerate(new_values):
            output_objects = []
            for j, value in enumerate(output_values):
                #unique = object()
                unique = (self, i, j)
                param = unique if (self.opt_index == 0) else value
                output_objects.append(OptimisticObject.from_opt(value, param))
            results.append(self.external._Result(self, output_objects, opt_index=self.opt_index))
        return results
    def __repr__(self):
        return '{}:{}->{}'.format(self.external.name, self.input_objects, self.external.outputs)

class Stream(External):
    _Instance = StreamInstance
    _Result = StreamResult
    def __init__(self, name, gen_fn, inputs, domain, outputs, certified, info):
        if info is None:
            info = StreamInfo(p_success=None, overhead=None)
        for p, c in Counter(outputs).items():
            if c != 1:
                raise ValueError('Output [{}] for stream [{}] is not unique'.format(p, name))
        for p in set(inputs) & set(outputs):
            raise ValueError('Parameter [{}] for stream [{}] is both an input and output'.format(p, name))
        parameters = {a for i in certified for a in get_args(i) if is_parameter(a)}
        for p in (parameters - set(inputs + outputs)):
            raise ValueError('Parameter [{}] for stream [{}] is not included within outputs'.format(p, name))
        super(Stream, self).__init__(name, info, inputs, domain)
        # Each stream could certify a stream-specific fact as well
        if gen_fn == DEBUG:
            #gen_fn = from_fn(lambda *args: tuple(object() for _ in self.outputs))
            gen_fn = from_fn(lambda *args: tuple(DebugValue(name, args, o) for o in self.outputs))
        self.gen_fn = gen_fn
        self.outputs = tuple(outputs)
        self.certified = tuple(certified)
        self.constants.update(a for i in certified for a in get_args(i) if not is_parameter(a))

        # TODO: generalize to a hierarchical sequence
        always_unique = False
        if always_unique:
            self.num_opt_fns = 0
            #self.opt_list_fn = get_unique_fn(self)
            self.opt_gen_fn = get_constant_gen_fn(self, None)
        else:
            self.num_opt_fns = 1
            self.opt_gen_fn = get_shared_gen_fn(self) if (self.info.opt_gen_fn is None) else self.info.opt_gen_fn
        #self.bound_list_fn = None
        #self.opt_fns = [get_unique_fn(self), get_shared_fn(self)] # get_unique_fn | get_shared_fn
        #self.opt_fns = [get_unique_fn(self)] # get_unique_fn | get_shared_fn
    def __repr__(self):
        return '{}:{}->{}'.format(self.name, self.inputs, self.outputs)

##################################################

# TODO: WildStream, FactStream

# class WildResult(object):
#     def __init__(self, stream_instance, output_objects):
#         self.stream_instance = stream_instance
#         #mapping = dict(list(zip(self.stream_instance.stream.inputs, self.stream_instance.input_objects)) +
#         #            list(zip(self.stream_instance.stream.outputs, output_objects)))
#         #self.certified = substitute_expression(self.stream_instance.stream.certified, mapping)
#     def get_certified(self):
#         #return self.certified
#     def __repr__(self):
#         #return '{}:{}->{}'.format(self.stream_instance.stream.name,
#         #                          str_from_tuple(self.stream_instance.input_objects),
#         #                          list(self.certified))
#
# def next_certified(self, **kwargs):
#     if self._generator is None:
#         self._generator = self.stream.gen_fn(*self.get_input_values())
#     new_certified = []
#     if isinstance(self._generator, FactGenerator):
#         new_certified += list(map(obj_from_value_expression, self._generator.generate(context=None)))
#         self.enumerated = self._generator.enumerated
#     else:
#         for output_objects in self.next_outputs(**kwargs):
#             mapping = dict(list(zip(self.stream.inputs, self.input_objects)) +
#                            list(zip(self.stream.outputs, output_objects)))
#             new_certified += substitute_expression(self.stream.certified, mapping)
#     return new_certified

##################################################

STREAM_ATTRIBUTES = [':stream', ':inputs', ':domain', ':outputs', ':certified']

def parse_stream(lisp_list, stream_map, stream_info):
    attributes = [lisp_list[i] for i in range(0, len(lisp_list), 2)]
    assert (STREAM_ATTRIBUTES == attributes)
    values = [lisp_list[i] for i in range(1, len(lisp_list), 2)]
    name, inputs, domain, outputs, certified = values
    if stream_map == DEBUG:
        gen_fn = DEBUG
    else:
        if name not in stream_map:
            raise ValueError('Undefined stream conditional generator: {}'.format(name))
        gen_fn = stream_map[name]
    return Stream(name, gen_fn, tuple(inputs), list_from_conjunction(domain),
                  tuple(outputs), list_from_conjunction(certified), stream_info.get(name, None))


def parse_stream_pddl(stream_pddl, stream_map, stream_info):
    streams = []
    if stream_pddl is None:
        return None, streams
    if all(isinstance(e, External) for e in stream_pddl):
        return None, stream_pddl
    if stream_map != DEBUG:
        stream_map = {k.lower(): v for k, v in stream_map.items()}
    stream_info = {k.lower(): v for k, v in stream_info.items()}
    stream_iter = iter(parse_lisp(stream_pddl))
    assert('define' == next(stream_iter))
    pddl_type, stream_name = next(stream_iter)
    assert('stream' == pddl_type)

    for lisp_list in stream_iter:
        name = lisp_list[0]
        if name == ':stream':
            external = parse_stream(lisp_list, stream_map, stream_info)
        elif name == ':wild':
            raise NotImplementedError(name)
        elif name == ':rule':
            continue
            # TODO: implement rules
            # TODO: add eager stream if multiple conditions otherwise apply and add to stream effects
        elif name == ':function':
            external = parse_function(lisp_list, stream_map, stream_info)
        elif name == ':predicate': # Cannot just use args if want a bound
            external = parse_predicate(lisp_list, stream_map, stream_info)
        else:
            raise ValueError(name)
        if any(e.name == external.name for e in streams):
            raise ValueError('Stream [{}] is not unique'.format(external.name))
        streams.append(external)
    return stream_name, streams
