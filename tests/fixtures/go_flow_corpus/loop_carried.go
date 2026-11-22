package main

func loopCarriedRead(count int, shouldAssign bool) int {
	var state *int
	for index := 0; index < count; index++ {
		if shouldAssign {
			state = new(int)
		}
		_ = *state // want: unassigned state
	}
	return *state // want: unassigned state
}
