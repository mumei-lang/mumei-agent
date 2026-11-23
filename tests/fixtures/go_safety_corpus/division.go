package main

func Div(a int, b int) int {
	return a / b // want: division_by_zero b
}

func Mod(a, b int) int {
	return a % b // want: division_by_zero b
}

func DivGuarded(a, b int) int {
	if b == 0 {
		return 0
	}
	return a / b
}

func DivGuardedOnWrongBranch(a, b int) int {
	if b == 0 {
		return a / b // want: division_by_zero b
	}
	return 0
}

func DivByLiteral(a int) int {
	return a / 4
}

const width = 8

func DivByConstant(a int) int {
	return a / width
}

func DivByZeroConstantExpr(a int) int {
	const zero = width - 8
	return a / zero // want: division_by_zero zero
}

func DivByLenOfEmptyable(a int, xs []int) int {
	return a / len(xs) // want: division_by_zero len(xs)
}

func DivByLenAfterEmptyGuard(a int, xs []int) int {
	if len(xs) == 0 {
		return 0
	}
	return a / len(xs)
}

func DivFloat(a, b float64) float64 {
	return a / b
}

func DivByReassignedNonzero(a, b int) int {
	if b == 0 {
		b = 1
	}
	return a / b
}

func DivAfterGuardThenReassign(a, b, c int) int {
	if b == 0 {
		return 0
	}
	b = c
	return a / b // want: division_by_zero b
}

func DivInLoopGuardedByCondition(a int, n int) int {
	total := 0
	for i := 1; i <= n; i++ {
		total += a / i
	}
	return total
}
