require_relative "../lib/calc"

RSpec.describe Calc do
  it "double trois" do
    expect(Calc.double(3)).to eq(6)
  end
end
