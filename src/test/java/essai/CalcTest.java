package essai;

import static org.junit.jupiter.api.Assertions.assertEquals;

import org.junit.jupiter.api.Disabled;
import org.junit.jupiter.api.Test;

class CalcTest {
    @Test
    void doublerMultiplieParDeux() {
        assertEquals(4, Calc.doubler(2));
    }

    @Test
    void suivantAjouteUn() {
        assertEquals(2, Calc.suivant(1));
    }
    // FIN DES TESTS
}
