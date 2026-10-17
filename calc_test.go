package calc

import "testing"

func TestDouble(t *testing.T) {
	if got := Double(2); got != 4 {
		t.Errorf("Double(2) = %d", got)
	}
}

func TestSuivant(t *testing.T) {
	if got := Suivant(1); got != 2 {
		t.Fatalf("Suivant(1) = %d", got)
	}
}

// FIN DES TESTS
