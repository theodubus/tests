using Calc;
using Xunit;

namespace Calc.Tests;

public class CalcTests
{
    [Fact]
    public void DoublerMultiplieParDeux()
    {
        Assert.Equal(4, Calcul.Doubler(2));
    }

    [Fact]
    public void SuivantAjouteUn()
    {
        Assert.Equal(2, Calcul.Suivant(1));
    }
    // FIN DES TESTS
}
