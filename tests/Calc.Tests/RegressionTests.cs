using Calc;
using Xunit;

namespace Calc.Tests;

public class RegressionTests
{
    [Fact]
    public void DoublerDeTrois()
    {
        Assert.Equal(6, Calcul.Doubler(3));
    }
}
