
def goal_to_string(goal):
    if isinstance(goal, basestring):
        return goal
    return "(" + " ".join(map(lambda x: goal_to_string(x), goal)) + ")"


def create_pddl_string(init_state, goal, domain_name, problem_name):
    objects = set()
    for pred in init_state:
        objects = objects.union(pred[1:])
    return '''
(define (problem {})
    (:domain {})
    (:objects
        {}
    )
    (:init
        {}
    )
    (:goal
        {}
    )
)'''.format(problem_name, domain_name, '\n\t'.join(objects), '\n\t'.join(map(lambda x: "(" + ' '.join(x) + ")", init_state)), goal_to_string(goal))


def create_pddl(init_state, goal, domain_name, problem_name, out_file):
    with open(out_file, 'w') as f:
        f.write(
            create_pddl_string(init_state, goal, domain_name, problem_name))


def get_tiles(prefix, length):
    return list(map(lambda x: prefix + str(x), range(length)))


def connect_tiles(tiles, direction, reverse_direction):
    predicates = []
    for current_tile, next_tile in zip(tiles, tiles[1:]):
        predicates.append((direction, current_tile, next_tile))
        predicates.append((reverse_direction, next_tile, current_tile))
    return predicates


def generate_corridor(length):
    tiles = ['start_tile'] + get_tiles('t', length) + ['goal_tile']
    last_tile = 't' + str(length - 1)
    predicates = [('empty', t) for t in tiles]
    predicates += [('person', 'person1'), ('at', 'person1', 'start_tile')]
    predicates += connect_tiles(tiles, 'east', 'west')
    return predicates, ('at', 'person1', 'goal_tile')


def create_corridor_pddl(length, out_file):
    init, goal = generate_corridor(length)
    create_pddl(init, goal, 'maze', 'corridor' + str(length), out_file)

# def generate_T(corridor_length, goal_length, deadend_length):
#     '''
#     structured in the following way:
#     there are `corridor_length` tiles until the fork,
#     at the fork:
#      `goal_length` cells north to the goal
#      `deadend_length` cells south to a deadend
#     '''
#     corridor_tiles = ['start_tile'] + get_tiles('c', corridor_length - 1)
#     goal_tiles = get_tiles('g', goal_length - 1) + ['goal_tile']
#     deadend_tiles = get_tiles('d', deadend_length)
#     tiles = corridor_tiles + goal_tiles + deadend_tiles
#     predicates = ['(empty {})'.format(t) for t in tiles] +
#         connect_tiles(corridor_tiles, 'east', 'west') +
#         connect_tiles(goal_tiles, 'north', 'south') +
#         connect_tiles(deadend_tiles, 'south', 'north')

#     fork = corridor_tiles[-1]
#     predicates.append('(north {} {})'.format(fork, goal_tiles[0]))
#     predicates.append('(south {1} {0})'.format(fork, goal_tiles[0]))

#     predicates.append('(south {} {})'.format(fork, deadend_tiles[0]))
#     predicates.append('(north {1} {0})'.format(fork, deadend_tiles[0]))

#     path = 'experiments/problems/t_{}_{}_{}.pddl'.format(
#         corridor_length, goal_length, deadend_length)
#     create_pddl(tiles, predicates, path)
#     return path

if __name__ == '__main__':
    length = 1
    create_corridor_pddl(5, 'tmp.pddl')
    # init, goal = generate_corridor(length)
    # print create_pddl_string(init, goal, 'maze', 'corridor' + str(length))
    # generate_T(5, 5, 5)
