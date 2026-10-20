namespace Calc;

public static class Calcul
{
    public static int Doubler(int x)
    {
        return 2 * x;
    }

    public static int Suivant(int x)
    {
        if (x > 100)
        {
            return x;
        }
        return Aide(x);
    }

    private static int Aide(int x)
    {
        return x + 1;
    }
}
