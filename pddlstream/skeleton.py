import time
from collections import defaultdict, namedtuple
from heapq import heappush, heappop
from itertools import product

from pddlstream.algorithm import add_certified
from pddlstream.conversion import evaluation_from_fact, substitute_expression
from pddlstream.function import FunctionResult, PredicateResult
from pddlstream.instantiation import Instantiator
from pddlstream.synthesizer import SynthStreamResult
from pddlstream.stream import StreamResult
from pddlstream.utils import elapsed_time, HeapElement

def get_stream_plan_index(stream_plan):
    if not stream_plan:
        return 0
    return max(r.opt_index for r in stream_plan)

def is_double_bound(stream_instance, double_bindings):
    if double_bindings is None:
        return True
    bindings = [double_bindings[o] for o in stream_instance.input_objects if o in double_bindings]
    return len(set(bindings)) != len(bindings)

def optimistic_process_streams(evaluations, streams, double_bindings=None):
    instantiator = Instantiator(evaluations, streams)
    stream_results = []
    while instantiator.stream_queue:
        stream_instance = instantiator.stream_queue.popleft()
        if not is_double_bound(stream_instance, double_bindings):
            continue
        for stream_result in stream_instance.next_optimistic():
            for fact in stream_result.get_certified():
                instantiator.add_atom(evaluation_from_fact(fact))
            stream_results.append(stream_result) # TODO: don't readd if all repeated facts?
    return stream_results

##################################################

# TODO: can either entirely replace arguments on plan or just pass bindings
# TODO: handle this in a partially ordered way
# TODO: no point not doing all at once if unique
# TODO: alternatively store just preimage and reachieve

SkeletonKey = namedtuple('SkeletonKey', ['attempts', 'length'])
Skeleton = namedtuple('Skeleton', ['instance', 'num_processed', 'bindings',
                                   'stream_plan', 'action_plan', 'cost'])

def instantiate_first(bindings, stream_plan):
    if not stream_plan:
        return None
    opt_result = stream_plan[0] # TODO: could do several at once but no real point
    input_objects = [bindings.get(i, i) for i in opt_result.instance.input_objects]
    instance = opt_result.instance.external.get_instance(input_objects)
    instance.disabled = True
    return instance

def bind_plan(bindings, plan):
    return [(name, tuple(bindings.get(o, o) for o in args)) for name, args in plan]

def proccess_stream_plan(key, sampling_problem, queue, evaluations, store):
    instance, num_processed, bindings, stream_plan, action_plan, cost = sampling_problem
    if not stream_plan:
        store.add_plan(bind_plan(bindings, action_plan), cost)
        return
    if store.best_cost <= cost:
        instance.disabled = False # TODO: only disable if not used elsewhere
        # TODO: could just hash instances
        return
    opt_result = stream_plan[0] # TODO: could do several at once but no real point
    assert(not any(evaluation_from_fact(f) not in evaluations for f in instance.get_domain()))
    # TODO: hash combinations to prevent repeats

    results = []
    for i in range(num_processed, len(instance.results_history)):
        results.extend(instance.results_history[i])
    if not results and not instance.enumerated:
        #print(key.attempts, key.length)
        results = instance.next_results(verbose=store.verbose)
    for result in results:
        add_certified(evaluations, result)
        if (type(result) is PredicateResult) and (opt_result.value != result.value):
            continue # TODO: check if satisfies target certified
        new_bindings = bindings.copy()
        if isinstance(result, StreamResult):
            for opt, obj in zip(opt_result.output_objects, result.output_objects):
                assert(opt not in new_bindings) # TODO: return failure if conflicting bindings
                new_bindings[opt] = obj
        new_stream_plan = stream_plan[1:]
        new_cost = cost
        if type(result) is FunctionResult:
            new_cost += (result.value - opt_result.value)
        new_key = SkeletonKey(0, len(new_stream_plan))
        new_skeleton = Skeleton(instantiate_first(new_bindings, new_stream_plan), 0,
                                new_bindings, new_stream_plan, action_plan, new_cost)
        heappush(queue, HeapElement(new_key, new_skeleton))

    if (key.attempts == 0) and isinstance(opt_result, SynthStreamResult): # TODO: only add if failure?
        new_stream_plan = opt_result.decompose() + stream_plan[1:]
        new_key = SkeletonKey(0, len(new_stream_plan))
        new_skeleton = Skeleton(instantiate_first(bindings, new_stream_plan), 0,
                                bindings, new_stream_plan, action_plan, cost)
        heappush(queue, HeapElement(new_key, new_skeleton))
    if not instance.enumerated:
        new_key = SkeletonKey(key.attempts + 1, len(stream_plan)) # TODO: compute expected sampling effort required
        new_skeleton = Skeleton(instance, len(instance.results_history),
                               bindings, stream_plan, action_plan, cost)
        heappush(queue, HeapElement(new_key, new_skeleton))

##################################################

def greedily_process_queue(queue, evaluations, store, max_time):
    # TODO: search until new disabled or new evaluation?
    start_time = time.time()
    while queue and not store.is_terminated():
        key, skeleton = queue[0]
        if (key.attempts != 0) and (max_time <= elapsed_time(start_time)):
            break
        heappop(queue)
        proccess_stream_plan(key, skeleton, queue, evaluations, store)

def fairly_process_queue(queue, evaluations, store):
    # TODO: max queue attempts?
    old_queue = list(queue)
    queue[:] = []
    for key, skeleton in old_queue:
        if store.is_terminated():
            break
        print('Attempts: {} | Length: {}'.format(key.attempts, key.length))
        proccess_stream_plan(key, skeleton, queue, evaluations, store)
        if store.is_terminated():
            break
        greedily_process_queue(queue, evaluations, store, 0)

##################################################

def optimistic_stream_grounding(stream_instance, bindings, evaluations, opt_evaluations, immediate=False):
    # TODO: combination for domain predicates
    evaluation_set = set(evaluations)
    opt_instances = []
    input_objects = [bindings.get(i, [i]) for i in stream_instance.input_objects]
    for combo in product(*input_objects):
        mapping = dict(zip(stream_instance.input_objects, combo))
        domain = set(map(evaluation_from_fact, substitute_expression(
            stream_instance.get_domain(), mapping))) # TODO: could just instantiate first
        if domain <= opt_evaluations:
            instance = stream_instance.external.get_instance(combo)
            if (instance.opt_index != 0) and (not immediate or (domain <= evaluation_set)):
                instance.opt_index -= 1
            opt_instances.append(instance)
    return opt_instances

def optimistic_process_stream_plan(evaluations, stream_plan):
    # TODO: can also use the instantiator and operate directly on the outputs
    # TODO: could bind by just using new_evaluations
    evaluations = set(evaluations)
    opt_evaluations = set(evaluations)
    opt_bindings = defaultdict(list)
    opt_results = []
    for opt_result in stream_plan:
        # TODO: could just do first step
        for instance in optimistic_stream_grounding(opt_result.instance, opt_bindings, evaluations, opt_evaluations):
            results = instance.next_optimistic()
            opt_evaluations.update(evaluation_from_fact(f) for r in results for f in r.get_certified())
            opt_results += results
            for result in results:
                if isinstance(result, StreamResult): # Could not add if same value
                    for opt, obj in zip(opt_result.output_objects, result.output_objects):
                        opt_bindings[opt].append(obj)
    return opt_results, opt_bindings