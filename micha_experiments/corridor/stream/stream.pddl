(define (stream maze)  
  (:stream find-far-east
    :inputs (?p ?a)
    :domain (at ?p ?a)
    :outputs (?b)
    :certified (far-east ?a ?b)
  )  
)