package main

func straightLineReadBeforeWrite() int {
	var state *int
	value := *state // want: unassigned state
	state = new(int)
	return value
}

func assignedButNeverRead() {
	value := 1 // want: unused value
}
