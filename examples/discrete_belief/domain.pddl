(define (domain belief)
  (:requirements :strips :equality)
  (:predicates
    (Location ?l)
    (BLoc ?o ?d)
    (MoveProb ?o ?d1 ?l1 ?l2 ?d2)
    (LookProb ?o ?d1 ?l ?ob ?d2)
    (GE ?o ?d ?l ?p)
    (BLocGE ?o ?l ?p)
    (BCollision ?l ?o ?d)
    (Unsafe ?l)
  )
  (:functions
    (MoveCost)
    (LookCost ?o ?d ?l ?ob)
  )
  (:action move
    :parameters (?o ?d1 ?l1 ?l2 ?d2)
    :precondition (and (MoveProb ?o ?d1 ?l1 ?l2 ?d2)
                       (BLoc ?o ?d1) (not (Unsafe ?l2)))
    :effect (and (BLoc ?o ?d2)
                 (not (BLoc ?o ?d1))
                 (increase (total-cost) (MoveCost)))
  )
  (:action look
    :parameters (?o ?d1 ?l ?ob ?d2)
    :precondition (and (LookProb ?o ?d1 ?l ?ob ?d2)
                       (BLoc ?o ?d1))
    :effect (and (BLoc ?o ?d2)
                 (not (BLoc ?o ?d1))
                 (increase (total-cost) (LookCost ?o ?d1 ?l ?ob)))
  )
  (:derived (BLocGE ?o ?l ?p)
    (exists (?d) (and (GE ?o ?d ?l ?p)
                      (Bloc ?o ?d)))
  )
  (:derived (Unsafe ?l) ; Could use the resulting distribution instead
    (exists (?o ?d) (and (Location ?l) (BCollision ?l ?o ?d) ; Include object do no self collisions?
                         (BLoc ?o ?d)))
  )
  ; (:derived (Unsafe2 ?l ?p1)
  ;   (exists (?o ?d ?p2) (and (Obj ?o) (Prob ?p1) (PCollision ?l ?d ?p2) (GE ?p1 ?p2) ;Strict?
  ;                       (BLoc ?o ?d)))
  ; )
)