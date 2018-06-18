#!/usr/bin/env python2.7

from __future__ import print_function
import sys
import os

from pddlstream.downward import solve_from_pddl
from pddlstream.incremental import solve_incremental, solve_exhaustive
from pddlstream.focused import solve_focused
from pddlstream.utils import print_solution, read

from problem_generator import generate_corridor, create_pddl

from pddlstream.stream import from_test, from_gen_fn


def read_pddl(filename):
    directory = os.path.dirname(os.path.abspath(__file__))
    return read(os.path.join(directory, filename))

#


def solve_pddl(domain_path, problem_path):
    domain_pddl = read_pddl(domain_path)
    problem_pddl = read_pddl(problem_path)

    plan, cost = solve_from_pddl(domain_pddl, problem_pddl)
    print('Plan:', plan)
    print('Cost:', cost)

#


def get_problem(init, goal):
    directory = os.path.dirname(os.path.abspath(__file__))

    domain_pddl = read_pddl('stream/domain.pddl')
    constant_map = {}
    stream_pddl = read(os.path.join(directory, 'stream', 'stream.pddl'))
    east_map = dict()
    for pred in init:
        if pred[0] == 'east':
            east_map[pred[1]] = pred[2]

    def gen_far_east(p, tile):
        current_far_east = test_simple_and_derived
        while current_far_east in east_map:
            print(current_far_east)
            next_east = east_map[current_far_east]
            current_far_east = next_east
            yield (next_east, )

    stream_map = {
        'find-far-east': from_gen_fn(gen_far_east),
    }

    return domain_pddl, constant_map, stream_pddl, stream_map, init, goal


def solve_simple(problem='simple/problem.pddl'):
    solve_pddl('simple/domain.pddl', problem)


def solve_derived(problem='derived/problem.pddl'):
    solve_pddl('derived/domain.pddl', problem)


def solve_stream(init, goal, focused=True):
    pddlstream_problem = get_problem(init, goal)
    if focused:
        solution = solve_focused(pddlstream_problem, unit_costs=True)
    else:
        # solution = solve_exhaustive(pddlstream_problem, unit_costs=True)
        solution = solve_incremental(pddlstream_problem, unit_costs=True)
    print_solution(solution)


import time
from contextlib import contextmanager
from timeit import default_timer


@contextmanager
def elapsed_timer():
    start = default_timer()
    elapser = lambda: default_timer() - start
    yield lambda: elapser()
    end = default_timer()
    elapser = lambda: end - start


def test_simple_and_derived():
    length = 1000
    init, goal = generate_corridor(length)
    name = 'corridor' + str(length)
    problem_path = os.path.abspath(
        os.path.join('micha_experiments', 'corridor', 'problems', name + '.pddl'))
    create_pddl(init, goal, 'maze', name, problem_path)
    with elapsed_timer() as elapsed1:
        solve_simple(problem_path)
    with elapsed_timer() as elapsed2:
        solve_derived(problem_path)
    print("simple done at %.2f seconds" % elapsed1())
    print("derived done at %.2f seconds" % elapsed2())


def main():
    length = 10
    init, goal = generate_corridor(length)
    name = 'corridor' + str(length)
    problem_path = os.path.abspath(
        os.path.join('micha_experiments', 'corridor', 'problems', name + '.pddl'))

    # create_pddl(init, goal, 'maze', name, problem_path)
    with elapsed_timer() as elapsed1:
        solve_stream(init, goal, False)
    with elapsed_timer() as elapsed2:
        solve_stream(init, goal)
    print("incremental stream done at %.2f seconds" % elapsed1())
    print("focused stream done at %.2f seconds" % elapsed2())

if __name__ == '__main__':
    main()
