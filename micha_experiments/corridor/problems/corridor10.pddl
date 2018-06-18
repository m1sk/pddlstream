
(define (problem corridor10)
    (:domain maze)
    (:objects
        t8
	t9
	t6
	t7
	t4
	t5
	t2
	t3
	t0
	start_tile
	person1
	goal_tile
	t1
    )
    (:init
        (empty start_tile)
	(empty t0)
	(empty t1)
	(empty t2)
	(empty t3)
	(empty t4)
	(empty t5)
	(empty t6)
	(empty t7)
	(empty t8)
	(empty t9)
	(empty goal_tile)
	(person person1)
	(at person1 start_tile)
	(east start_tile t0)
	(west t0 start_tile)
	(east t0 t1)
	(west t1 t0)
	(east t1 t2)
	(west t2 t1)
	(east t2 t3)
	(west t3 t2)
	(east t3 t4)
	(west t4 t3)
	(east t4 t5)
	(west t5 t4)
	(east t5 t6)
	(west t6 t5)
	(east t6 t7)
	(west t7 t6)
	(east t7 t8)
	(west t8 t7)
	(east t8 t9)
	(west t9 t8)
	(east t9 goal_tile)
	(west goal_tile t9)
    )
    (:goal
        (at person1 goal_tile)
    )
)