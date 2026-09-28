# PrismML Experimental

This directory records the PrismML ternary model experiment.

## Model tested

Ternary-Bonsai-2-27B-PTQ1_0.gguf

Format:
- PTQ1_0
- 1.75 bpw ternary
- group 128

## Runtime

Custom llama.cpp PrismML fork:
- build: b10743-adfffbe41

## Result

The experiment successfully loaded and executed the ternary model.

Observed issues:
- very low generation speed
- poor instruction following
- unexpected output behavior
- no demonstrated advantage over stock llama.cpp runtime

Conclusion:
PrismML remains an isolated experimental runtime unless future models require it.
