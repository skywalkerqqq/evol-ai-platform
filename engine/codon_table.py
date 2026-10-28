"""密码子表与遗传密码。

密码子使用频率取自 Kazusa 人类密码子使用表（相对频率，同一氨基酸内归一化）。
数值用于同义替换时的偏好排序，不参与任何定量生物学结论。
"""

# ---- 标准遗传密码 ----
CODON_TABLE = {
    "UUU": "F", "UUC": "F", "UUA": "L", "UUG": "L",
    "CUU": "L", "CUC": "L", "CUA": "L", "CUG": "L",
    "AUU": "I", "AUC": "I", "AUA": "I", "AUG": "M",
    "GUU": "V", "GUC": "V", "GUA": "V", "GUG": "V",
    "UCU": "S", "UCC": "S", "UCA": "S", "UCG": "S",
    "CCU": "P", "CCC": "P", "CCA": "P", "CCG": "P",
    "ACU": "T", "ACC": "T", "ACA": "T", "ACG": "T",
    "GCU": "A", "GCC": "A", "GCA": "A", "GCG": "A",
    "UAU": "Y", "UAC": "Y", "UAA": "*", "UAG": "*",
    "CAU": "H", "CAC": "H", "CAA": "Q", "CAG": "Q",
    "AAU": "N", "AAC": "N", "AAA": "K", "AAG": "K",
    "GAU": "D", "GAC": "D", "GAA": "E", "GAG": "E",
    "UGU": "C", "UGC": "C", "UGA": "*", "UGG": "W",
    "CGU": "R", "CGC": "R", "CGA": "R", "CGG": "R",
    "AGU": "S", "AGC": "S", "AGA": "R", "AGG": "R",
    "GGU": "G", "GGC": "G", "GGA": "G", "GGG": "G",
}

# DNA 版本（T 代替 U）
DNA_CODON_TABLE = {c.replace("U", "T"): aa for c, aa in CODON_TABLE.items()}

# 人类相对同义密码子使用频率（Kazusa）
HUMAN_USAGE = {
    "TTT": 0.45, "TTC": 0.55, "TTA": 0.07, "TTG": 0.13,
    "CTT": 0.13, "CTC": 0.20, "CTA": 0.07, "CTG": 0.41,
    "ATT": 0.36, "ATC": 0.48, "ATA": 0.16, "ATG": 1.00,
    "GTT": 0.18, "GTC": 0.24, "GTA": 0.11, "GTG": 0.47,
    "TCT": 0.18, "TCC": 0.22, "TCA": 0.15, "TCG": 0.06,
    "CCT": 0.28, "CCC": 0.33, "CCA": 0.27, "CCG": 0.11,
    "ACT": 0.24, "ACC": 0.36, "ACA": 0.28, "ACG": 0.11,
    "GCT": 0.26, "GCC": 0.40, "GCA": 0.23, "GCG": 0.11,
    "TAT": 0.43, "TAC": 0.57, "TAA": 0.28, "TAG": 0.20,
    "CAT": 0.41, "CAC": 0.59, "CAA": 0.27, "CAG": 0.73,
    "AAT": 0.46, "AAC": 0.54, "AAA": 0.42, "AAG": 0.58,
    "GAT": 0.46, "GAC": 0.54, "GAA": 0.42, "GAG": 0.58,
    "TGT": 0.45, "TGC": 0.55, "TGA": 0.52, "TGG": 1.00,
    "CGT": 0.08, "CGC": 0.18, "CGA": 0.06, "CGG": 0.20,
    "AGT": 0.15, "AGC": 0.24, "AGA": 0.21, "AGG": 0.20,
    "GGT": 0.16, "GGC": 0.34, "GGA": 0.25, "GGG": 0.25,
}

# 氨基酸 -> 同义密码子列表
AA_TO_CODONS = {}
for _codon, _aa in DNA_CODON_TABLE.items():
    AA_TO_CODONS.setdefault(_aa, []).append(_codon)

# 人类基因组中偏低的密码子（用于分析阶段的「稀有密码子」提示）
RARE_CODONS = {"CGA", "CGT", "ATA", "CTA", "TTA", "TCG", "CCG", "ACG", "GTA"}


def translate(dna: str) -> str:
    """按标准表翻译；长度非 3 倍数时忽略尾部不完整密码子。"""
    dna = dna.upper().replace("U", "T")
    aa = []
    for i in range(0, len(dna) - 2, 3):
        aa.append(DNA_CODON_TABLE.get(dna[i:i + 3], "X"))
    return "".join(aa)
