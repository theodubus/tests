<?php

namespace Essai\Tests;

use Essai\Calc;
use PHPUnit\Framework\TestCase;

final class CalcTest extends TestCase
{
    public function testDouble(): void
    {
        $this->assertSame(4, Calc::double(2));
    }

    public function testSuivant(): void
    {
        $this->assertSame(2, Calc::suivant(1));
    }
    // FIN DES TESTS
}
