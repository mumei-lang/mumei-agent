package main

func typeSwitchNoDefault(value any) int {
	var state *int
	switch value.(type) {
	case int:
		state = new(int)
	}
	return *state // want: unassigned state
}

func typeSwitchWithDefault(value any) int {
	var state *int
	switch value.(type) {
	case int:
		state = new(int)
	default:
		state = new(int)
	}
	return *state
}
