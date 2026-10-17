package essai;

public class Calc {
    public static int doubler(int x) {
        return 2 * x;
    }

    public static int suivant(int x) {
        if (x > 100) {
            return x;
        }
        return aide(x);
    }

    private static int aide(int x) {
        return x + 1;
    }
}
