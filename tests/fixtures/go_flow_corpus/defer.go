package main

func deferReadsValue(value int) {}

func deferReadsMaybeUnassigned(condition bool) int {
	var state *int
	if condition {
		state = new(int)
	}
	defer deferReadsValue(*state) // want: unassigned state
	return 0
}
