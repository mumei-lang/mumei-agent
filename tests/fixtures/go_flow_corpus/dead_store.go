package main

func deadStoreOverwritten() int {
	value := 1 // want: unused value
	value = 2
	return value
}
