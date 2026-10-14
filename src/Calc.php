<?php

namespace Essai;

final class Calc
{
    public static function double(int $x): int
    {
        return 2 * $x;
    }

    public static function suivant(int $x): int
    {
        if ($x > 100) {
            return $x;
        }
        return self::aide($x);
    }

    private static function aide(int $x): int
    {
        return $x + 1;
    }
}
