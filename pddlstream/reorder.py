from collections import namedtuple, deque
from heapq import heappush, heappop

from pddlstream.algorithm import neighbors_from_orders
from pddlstream.conversion import evaluation_from_fact, get_prefix, EQ, pddl_from_object
from pddlstream.downward import get_init, task_from_domain_problem, get_problem, fd_from_fact, is_applicable, \
    apply_action
from pddlstream.function import PredicateResult, Result
from pddlstream.scheduling.relaxed import instantiate_axioms, get_achieving_axioms, extract_axioms
from pddlstream.scheduling.simultaneous import evaluations_from_stream_plan
from pddlstream.stream import StreamResult
from pddlstream.utils import INF, Verbose, MockSet, find_unique, implies, HeapElement


def get_partial_orders(stream_plan):
    # TODO: only show the first atom achieved?
    partial_orders = set()
    for i, stream1 in enumerate(stream_plan):
        for stream2 in stream_plan[i+1:]: # Prevents circular
            if set(stream1.get_certified()) & set(stream2.instance.get_domain()):
                partial_orders.add((stream1, stream2))
    return partial_orders

##################################################

def topological_sort(vertices, orders, priority_fn=lambda v: 0):
    # Can also do a DFS version
    incoming_edges, outgoing_edges = neighbors_from_orders(orders)
    ordering = []
    queue = []
    for v in vertices:
        if not incoming_edges[v]:
            heappush(queue, HeapElement(priority_fn(v), v))
    while queue:
        v1 = heappop(queue).value
        ordering.append(v1)
        for v2 in outgoing_edges[v1]:
            incoming_edges[v2].remove(v1)
            if not incoming_edges[v2]:
                heappush(queue, HeapElement(priority_fn(v2), v2))
    return ordering

##################################################

def get_stream_stats(result):
    return result.instance.get_p_success(), result.instance.get_overhead()

def compute_expected_cost(stream_plan, stats_fn=get_stream_stats):
    if stream_plan is None:
        return INF
    expected_cost = 0
    for result in reversed(stream_plan):
        p_success, overhead = stats_fn(result)
        expected_cost = overhead + p_success * expected_cost
    return expected_cost

# TODO: include context here as a weak constraint
# TODO: actions as a weak constraint
# TODO: works in the absence of partial orders
# TODO: actions are extremely unlikely to work
# TODO: can give actions extreme priority
# TODO: can also more manually reorder

Subproblem = namedtuple('Subproblem', ['cost', 'head', 'subset'])

def dynamic_programming(vertices, valid_head_fn, stats_fn, prune=True, greedy=False):
    # 2^N rather than N!
    # TODO: can just do on the infos themselves
    dominates = lambda v1, v2: all(s1 <= s2 for s1, s2 in zip(stats_fn(v1), stats_fn(v2)))
    effort_orders = set()
    if prune:
        for i, v1 in enumerate(vertices):
            for v2 in vertices[i+1:]:
                if dominates(v1, v2):
                    effort_orders.add((v1, v2)) # Includes equality
                elif dominates(v2, v1):
                    effort_orders.add((v2, v1))
    _, out_priority_orders = neighbors_from_orders(effort_orders)
    priority_ordering = topological_sort(vertices, effort_orders)[::-1]

    # TODO: could the greedy strategy lead to premature choices
    subset = frozenset()
    queue = deque([subset]) # Acyclic because subsets
    subproblems = {subset: Subproblem(0, None, None)}
    while queue:
        subset = queue.popleft()
        applied = set()
        for v in priority_ordering:
            if greedy and applied:
                break
            if (v not in subset) and valid_head_fn(v, subset) and not (out_priority_orders[v] & applied):
                applied.add(v)
                new_subset = frozenset([v]) | subset
                p_success, overhead = stats_fn(v)
                new_cost = overhead + p_success*subproblems[subset].cost
                subproblem = Subproblem(new_cost, v, subset)  # Adds new element to the front
                if new_subset not in subproblems:
                    queue.append(new_subset)
                    subproblems[new_subset] = subproblem
                elif new_cost < subproblems[new_subset].cost:
                    subproblems[new_subset] = subproblem

    ordering = []
    subset = frozenset(vertices)
    while True:
        if subset not in subproblems:
            print(vertices)
            # TODO: some sort of bug where the problem isn't solved?
        subproblem = subproblems[subset]
        if subproblem.head is None:
            break
        ordering.append(subproblem.head)
        subset = subproblem.subset
    return ordering

##################################################

def reorder_stream_plan(stream_plan, **kwargs):
    if stream_plan is None:
        return None
    stream_orders = get_partial_orders(stream_plan)
    in_stream_orders, out_stream_orders = neighbors_from_orders(stream_orders)
    valid_combine = lambda v, subset: out_stream_orders[v] <= subset
    #valid_combine = lambda v, subset: in_stream_orders[v] & subset
    return dynamic_programming(stream_plan, valid_combine, get_stream_stats, **kwargs)

def reorder_combined_plan(evaluations, combined_plan, action_info, domain, **kwargs):
    if combined_plan is None:
        return None
    stream_plan, action_plan = separate_plan(combined_plan)
    orders = get_combined_orders(evaluations, stream_plan, action_plan, domain)
    _, out_orders = neighbors_from_orders(orders)
    valid_combine = lambda v, subset: out_orders[v] <= subset
    def stats_fn(operator):
        if isinstance(operator, Result):
            return get_stream_stats(operator)
        name, _ = operator
        info = action_info[name]
        return info.p_success, info.overhead
    return dynamic_programming(combined_plan, valid_combine, stats_fn, **kwargs)


def get_stream_instances(stream_plan):
    import pddl
    # TODO: something that inverts the negative items
    stream_instances = [] # TODO: could even apply these to the state directly
    for result in stream_plan:
        name = result.instance.external.name
        precondition = list(map(fd_from_fact, result.instance.get_domain()))
        effects = [([], fd_from_fact(fact)) for fact in result.get_certified() if not get_prefix(fact) == EQ]
        cost = None # TODO: effort?
        instance = pddl.PropositionalAction(name, precondition, effects, cost)
        stream_instances.append(instance)
    return stream_instances


def get_action_instances(task, action_plan):
    import pddl
    import instantiate
    type_to_objects = instantiate.get_objects_by_type(task.objects, task.types)
    function_assignments = {f.fluent: f.expression for f in task.init
                            if isinstance(f, pddl.f_expression.FunctionAssignment)}
    fluent_facts = MockSet()
    init_facts = set()
    action_instances = []
    for name, objects in action_plan:
        # TODO: what if more than one action of the same name due to normalization?
        # Normalized actions have same effects, so I just have to pick one
        action = find_unique(lambda a: a.name == name, task.actions)
        args = map(pddl_from_object, objects)
        assert (len(action.parameters) == len(args))
        variable_mapping = {p.name: a for p, a in zip(action.parameters, args)}
        instance = action.instantiate(variable_mapping, init_facts,
                                      fluent_facts, type_to_objects,
                                      task.use_min_cost_metric, function_assignments)
        assert (instance is not None)
        action_instances.append(instance)
    return action_instances

def replace_derived(task, negative_init, action_instances):
    import pddl_to_prolog
    import build_model
    import axiom_rules
    import pddl

    actions = task.actions
    task.actions = []
    function_assignments = {f.fluent: f.expression for f in task.init
                            if isinstance(f, pddl.f_expression.FunctionAssignment)}
    task.init = (set(task.init) | {a.negate() for a in negative_init}) - set(function_assignments)
    fluent_facts = MockSet()
    for instance in action_instances:
        # TODO: just instantiate task?
        with Verbose(False):
            model = build_model.compute_model(pddl_to_prolog.translate(task))  # Changes based on init
        # fluent_facts = instantiate.get_fluent_facts(task, model)
        instantiated_axioms = instantiate_axioms(model, task.init, fluent_facts)

        goal_list = []  # TODO: include the goal?
        with Verbose(False):  # TODO: helpful_axioms prunes axioms that are already true (e.g. not Unsafe)
            helpful_axioms, axiom_init, _ = axiom_rules.handle_axioms([instance], instantiated_axioms, goal_list)
        axiom_from_atom = get_achieving_axioms(task.init | negative_init,
                                               helpful_axioms, axiom_init)
        # negated_from_name=negated_from_name)

        axiom_plan = []
        extract_axioms(axiom_from_atom, instance.precondition, axiom_plan)
        # TODO: what the propositional axiom has conditional derived
        axiom_pre = {p for ax in axiom_plan for p in ax.condition}
        axiom_eff = {ax.effect for ax in axiom_plan}
        instance.precondition = list((set(instance.precondition) | axiom_pre) - axiom_eff)

        assert (is_applicable(task.init, instance))
        apply_action(task.init, instance)
    task.actions = actions

def get_combined_orders(evaluations, stream_plan, action_plan, domain):
    if action_plan is None:
        return None
    # TODO: could just do this within relaxed
    # TODO: do I want to strip the fluents and just do the partial ordering?

    stream_instances = get_stream_instances(stream_plan)
    negative_results = filter(lambda r: isinstance(r, PredicateResult) and (r.value == False), stream_plan)
    negative_init = set(get_init((evaluation_from_fact(f) for r in negative_results
                                  for f in r.get_certified()), negated=True))
    #negated_from_name = {r.instance.external.name for r in negative_results}
    opt_evaluations = evaluations_from_stream_plan(evaluations, stream_plan)
    goal_expression = ('and',)
    task = task_from_domain_problem(domain, get_problem(opt_evaluations, goal_expression, domain, unit_costs=True))

    action_instances = get_action_instances(task, action_plan)
    replace_derived(task, negative_init, action_instances)

    #combined_instances = stream_instances + action_instances
    orders = set()
    for i, a1 in enumerate(action_plan):
        for a2 in action_plan[i+1:]:
            orders.add((a1, a2))
    # TODO: just store first achiever here
    for i, instance1 in enumerate(stream_instances):
        for j in range(i+1, len(stream_instances)):
            effects = {e for _, e in  instance1.add_effects}
            if effects & set(stream_instances[j].precondition):
                orders.add((stream_plan[i], stream_plan[j]))
    for i, instance1 in enumerate(stream_instances):
        for j, instance2 in enumerate(action_instances):
            effects = {e for _, e in  instance1.add_effects} | \
                      {e.negate() for _, e in  instance1.del_effects}
            if effects & set(instance2.precondition):
                orders.add((stream_plan[i], action_plan[j]))
    return orders

##################################################

def separate_plan(combined_plan, action_info=None, terminate=False, stream_only=True):
    if combined_plan is None:
        return None, None
    stream_plan = []
    action_plan = []
    terminated = False
    for operator in combined_plan:
        if terminate and terminated:
            break
        if isinstance(operator, Result):
            if terminated:
                if implies(stream_only, isinstance(operator, StreamResult)):
                    action_plan.append(operator.get_tuple())
            else:
                stream_plan.append(operator)
        else:
            action_plan.append(operator)
            if action_info is not None:
                name, _ = operator
                terminated |= action_info[name].terminal
    return stream_plan, action_plan

##################################################

"""
def partial_ordered(plan):
    # https://www.aaai.org/ocs/index.php/ICAPS/ICAPS10/paper/viewFile/1420/1539
    # http://repository.cmu.edu/cgi/viewcontent.cgi?article=1349&context=compsci
    # https://arxiv.org/pdf/1105.5441.pdf
    # https://pdfs.semanticscholar.org/e057/e330249f447c2f065cf50db9dfaddad16aaa.pdf
    # https://github.mit.edu/caelan/PAL/blob/master/src/search/post_processing.cc

    instances = instantiate_plan(plan)
    orders = set()
    primary_effects = set() # TODO: start and goal operators here?
    for i in reversed(xrange(len(instances))):
        for pre in instances[i].preconditions:
            for j in reversed(xrange(i)):
                #if pre in instances[j].effects:
                if any(eff == pre for eff in instances[j].effects):
                    orders.add((j, i))
                    primary_effects.add((j, pre))
                    break
        for eff in instances[i].effects:
            for j in xrange(i):
                if any((pre.head == eff.head) and (pre.value != eff.value) for pre in instances[j].preconditions):
                    orders.add((j, i))
            if (i, eff) in primary_effects:
                for j in xrange(i):
                    if any((eff2.head == eff.head) and (eff2.value != eff.value) for eff2 in instances[j].effects):
                        orders.add((j, i))
    # TODO: could remove transitive
    # TODO: this isn't so helpful because it will choose arbitrary streams until an action is feasible (i.e. not intelligent ones)
    for i, (action, args) in enumerate(plan):
        print i, action, args #, instances[i].preconditions, instances[i].effects
    print orders
    print primary_effects
    print topological_sort(range(len(plan)), orders, lambda v: hasattr(plan[v][0], 'stream'))
"""