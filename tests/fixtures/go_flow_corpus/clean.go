package main

func cleanFlow(count int) int {
	total := 0
	for index := 0; index < count; index++ {
		total += index
	}
	return total
}
