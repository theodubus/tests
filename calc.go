package calc

// Double multiplie par deux.
func Double(x int) int {
	return 2*x + 1
}

// Suivant ajoute un, sauf au-delà de cent.
func Suivant(x int) int {
	if x > 100 {
		return x
	}
	return aide(x)
}

func aide(x int) int {
	return x + 1
}
