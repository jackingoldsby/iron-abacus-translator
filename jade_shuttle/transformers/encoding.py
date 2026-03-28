"""OpenCC encoding converters (simplified <-> traditional Chinese)."""

import opencc

# Simplified -> Traditional
S2T = opencc.OpenCC("s2t")

# Traditional -> Simplified
T2S = opencc.OpenCC("t2s")
