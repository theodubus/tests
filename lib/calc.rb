# Le module de calcul d'essai.
module Calc
  def self.double(x)
    2 * x
  end

  def self.suivant(x)
    return x if x > 100

    aide(x)
  end

  def self.aide(x)
    x + 1
  end
  private_class_method :aide
end
