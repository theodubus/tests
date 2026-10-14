package essai;

import static org.junit.jupiter.api.Assertions.assertEquals;

import org.junit.jupiter.api.Test;

class RegressionTest {
    @Test
    void doublerDeTrois() {
        assertEquals(6, Calc.doubler(3));
    }
}
