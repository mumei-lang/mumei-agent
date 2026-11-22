package main

func expressionSwitchNoDefault(tag int) int {
	var state *int
	switch tag {
	case 0:
		state = new(int)
	}
	return *state // want: unassigned state
}

func expressionSwitchWithDefault(tag int) int {
	var state *int
	switch tag {
	case 0:
		state = new(int)
	default:
		state = new(int)
	}
	return *state
}
