from __future__ import print_function

from heapq import heappush

from pddlstream.algorithm import parse_problem, SolutionStore, has_costs
from pddlstream.instantiation import Instantiator
from pddlstream.conversion import revert_solution
from pddlstream.function import Function, Predicate
from pddlstream.synthesizer import get_synthetic_stream_plan
from pddlstream.exogenous import compile_to_exogenous
from pddlstream.postprocess import locally_optimize
from pddlstream.reorder import separate_plan, reorder_combined_plan, reorder_stream_plan
from pddlstream.scheduling.relaxed import relaxed_stream_plan
from pddlstream.scheduling.simultaneous import simultaneous_stream_plan, evaluations_from_stream_plan
from pddlstream.statistics import get_action_info, load_stream_statistics, \
    write_stream_statistics
from pddlstream.skeleton import optimistic_process_streams, instantiate_first, optimistic_process_stream_plan, \
    Skeleton, SkeletonKey, greedily_process_queue, fairly_process_queue, get_stream_plan_index
from pddlstream.utils import INF, HeapElement
from pddlstream.visualization import clear_visualizations, create_visualizations
from pddlstream.incremental import layered_process_stream_queue


# TODO: compute total stream plan p_success and overhead
# TODO: ensure search and sampling have equal time
# TODO: select whether to search or sample based on expected success rates
# TODO: estimate the success rate for a stream_plan given past outcomes
# TODO: make a subroutine that does commit

def partition_externals(externals):
    functions = list(filter(lambda s: type(s) is Function, externals))
    negative = list(filter(lambda s: type(s) is Predicate, externals)) # and s.is_negative()
    streams = list(filter(lambda s: s not in (functions + negative), externals))
    return streams, functions, negative

##################################################

# TODO: can instantiate all but subtract stream_results
# TODO: can even pass a subset of the fluent state
# TODO: can just compute the stream plan preimage
# TODO: replan constraining the initial state and plan skeleton
# TODO: reuse subproblems
# TODO: always start from the initial state (i.e. don't update)

# def stream_plan_preimage(stream_plan):
#     preimage = set()
#     for stream_result in reversed(stream_plan):
#         preimage -= set(stream_result.get_certified())
#         preimage |= set(stream_result.instance.get_domain())
#     return preimage

# TODO: check empty plan first?
def recursive_solve_stream_plan(evaluations, streams, functions, stream_results, solve_stream_plan, depth):
    combined_plan, cost = solve_stream_plan(stream_results)
    stream_plan, action_plan = separate_plan(combined_plan, action_info=None, terminate=False, stream_only=False)
    #print('Depth: {}\n'
    #      'Stream plan: {}\n'
    #      'Action plan: {}'.format(depth, stream_plan, action_plan))
    if stream_plan is None:
        return stream_plan, cost, depth
    plan_index = get_stream_plan_index(stream_plan)
    if plan_index == 0:
        return combined_plan, cost, depth
    stream_results, bindings = optimistic_process_stream_plan(evaluations, stream_plan)
    double_bindings = {v: k for k, values in bindings.items() if 2 <= len(values) for v in values}
    stream_results += optimistic_process_streams(evaluations_from_stream_plan(evaluations, stream_results),
                                                 streams, double_bindings=double_bindings)
    stream_results += optimistic_process_streams(evaluations_from_stream_plan(evaluations, stream_results),
                                                 functions)
    return recursive_solve_stream_plan(evaluations, streams, functions, stream_results, solve_stream_plan, depth + 1)

def iterative_solve_stream_plan(evaluations, streams, functions, solve_stream_plan):
    # TODO: option to toggle commit using max_depth?
    # TODO: constrain to use previous plan to some degree
    num_iterations = 0
    while True:
        num_iterations += 1
        stream_results = optimistic_process_streams(evaluations, streams + functions)
        combined_plan, cost, depth = recursive_solve_stream_plan(evaluations, streams, functions, stream_results, solve_stream_plan, 0)
        print('Attempt: {} | Results: {} | Depth: {} | Success: {}'.format(num_iterations, len(stream_results),
                                                                           depth, combined_plan is not None))
        if (combined_plan is not None) or (depth == 0):
            return combined_plan, cost

##################################################

def solve_focused(problem, stream_info={}, action_info={}, synthesizers=[],
                  max_time=INF, max_cost=INF, unit_costs=None, sampling_time=0,
                  effort_weight=None, eager_layers=1,
                  visualize=False, verbose=True, postprocess=False, **search_kwargs):
    """
    Solves a PDDLStream problem by first hypothesizing stream outputs and then determining whether they exist
    :param problem: a PDDLStream problem
    :param action_info: a dictionary from stream name to ActionInfo for planning and execution
    :param stream_info: a dictionary from stream name to StreamInfo altering how individual streams are handled
    :param max_time: the maximum amount of time to apply streams
    :param max_cost: a strict upper bound on plan cost
    :param effort_weight: a multiplier for stream effort compared to action costs
    :param eager_layers: the number of eager stream application layers per iteration
    :param visualize: if True, it draws the constraint network and stream plan as a graphviz file
    :param verbose: if True, this prints the result of each stream application
    :param search_kwargs: keyword args for the search subroutine
    :return: a tuple (plan, cost, evaluations) where plan is a sequence of actions
        (or None), cost is the cost of the plan, and evaluations is init but expanded
        using stream applications
    """
    # TODO: return to just using the highest level samplers at the start
    solve_stream_plan_fn = relaxed_stream_plan if effort_weight is None else simultaneous_stream_plan
    # TODO: warning check if using simultaneous_stream_plan or sequential_stream_plan with non-eager functions
    num_iterations = 0
    store = SolutionStore(max_time, max_cost, verbose) # TODO: include other info here?
    evaluations, goal_expression, domain, stream_name, externals = parse_problem(problem, stream_info)
    compile_to_exogenous(evaluations, domain, externals)
    if unit_costs is None:
        unit_costs = not has_costs(domain)
    full_action_info = get_action_info(action_info)
    load_stream_statistics(stream_name, externals + synthesizers)
    if visualize:
        clear_visualizations()
    eager_externals = list(filter(lambda e: e.info.eager, externals))
    streams, functions, negative = partition_externals(externals)
    queue = []
    # TODO: switch to searching if believe chance of search better than sampling
    while not store.is_terminated():
        num_iterations += 1
        # TODO: decide max_sampling_time based on total search_time or likelihood estimates
        print('\nIteration: {} | Queue: {} | Evaluations: {} | Cost: {} | Time: {:.3f}'.format(
            num_iterations, len(queue), len(evaluations), store.best_cost, store.elapsed_time()))
        layered_process_stream_queue(Instantiator(evaluations, eager_externals), evaluations, store, eager_layers)
        solve_stream_plan = lambda sr: solve_stream_plan_fn(evaluations, goal_expression, domain, sr,
                                                            negative,
                                                            max_cost=store.best_cost,
                                                            #max_cost=min(store.best_cost, max_cost),
                                                            unit_costs=unit_costs, **search_kwargs)
        #combined_plan, cost = solve_stream_plan(populate_results(evaluations, streams + functions))
        combined_plan, cost = iterative_solve_stream_plan(evaluations, streams, functions, solve_stream_plan)
        if action_info:
            combined_plan = reorder_combined_plan(evaluations, combined_plan, full_action_info, domain)
            print('Combined plan: {}'.format(combined_plan))
        stream_plan, action_plan = separate_plan(combined_plan, full_action_info)
        stream_plan = reorder_stream_plan(stream_plan) # TODO: is this strictly redundant?
        stream_plan = get_synthetic_stream_plan(stream_plan, synthesizers)
        print('Stream plan: {}\n'
              'Action plan: {}'.format(stream_plan, action_plan))

        if stream_plan is None:
            if queue:
                 fairly_process_queue(queue, evaluations, store)
            else:
                break
        else:
            if visualize:
                create_visualizations(evaluations, stream_plan, num_iterations)
            heappush(queue, HeapElement(SkeletonKey(0, len(stream_plan)),
                             Skeleton(instantiate_first({}, stream_plan), 0, {}, stream_plan, action_plan, cost)))
            greedily_process_queue(queue, evaluations, store, sampling_time)

    if postprocess and (not unit_costs):
        locally_optimize(evaluations, store, goal_expression, domain, functions, negative, synthesizers)
    write_stream_statistics(stream_name, externals + synthesizers, verbose)
    return revert_solution(store.best_plan, store.best_cost, evaluations)