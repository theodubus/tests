package calc

import "testing"

func TestDoubleDeTrois(t *testing.T) {
	if got := Double(3); got != 6 {
		t.Errorf("Double(3) = %d", got)
	}
}
