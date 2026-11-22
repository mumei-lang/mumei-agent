package main

func ifElsePartialAssignment(condition bool) int {
	var state *int
	if condition {
		state = new(int)
	} else {
	}
	return *state // want: unassigned state
}
