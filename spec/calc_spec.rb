require_relative "../lib/calc"

RSpec.describe Calc do
  it "multiplie par deux" do
    expect(Calc.double(2)).to eq(4)
  end

  it "ajoute un" do
    expect(Calc.suivant(1)).to eq(2)
  end
  # FIN DES TESTS
end
