package main

func forwardGotoSkipsWrite(skip bool) int {
	var state *int
	if skip {
		goto done
	}
	state = new(int)
done:
	return *state // want: unassigned state
}
