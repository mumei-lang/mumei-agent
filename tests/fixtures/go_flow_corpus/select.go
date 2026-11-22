package main

func selectBlocksUntilAssigned(ch <-chan struct{}) int {
	var state *int
	select {
	case <-ch:
		state = new(int)
	}
	return *state
}

func selectDefaultCanSkipAssignment(ch <-chan struct{}) int {
	var state *int
	select {
	case <-ch:
		state = new(int)
	default:
	}
	return *state // want: unassigned state
}
