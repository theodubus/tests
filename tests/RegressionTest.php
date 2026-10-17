<?php

namespace Essai\Tests;

use Essai\Calc;
use PHPUnit\Framework\TestCase;

final class RegressionTest extends TestCase
{
    public function testDoubleDeTrois(): void
    {
        $this->assertSame(6, Calc::double(3));
    }
}
