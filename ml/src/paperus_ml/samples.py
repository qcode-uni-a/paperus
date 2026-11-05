# ruff: noqa: E501 (one sample sentence per line)
"""Sample passages for measuring speed: research prose of the length
paperus embeds (about 250 words), varied so no two are the same."""

_SENTENCES = [
    "We study how blind zones below the radar beam hide light rainfall in mountain valleys.",
    "The model fills the missing reflectivity from neighbouring heights and nearby stations.",
    "Results are compared against rain gauges over three winters and two summer seasons.",
    "Errors grow with distance from the radar and with the height of the lowest usable beam.",
    "Die Messungen zeigen, dass flache Niederschläge in Tälern häufig unterschätzt werden.",
    "A diffusion model trained on complete scans learns the vertical structure of storms.",
    "We release the code and the data, so that other groups can repeat every experiment.",
    "Uncertainty is estimated from an ensemble of twenty samples for each missing column.",
    "Les résultats confirment l'intérêt de la méthode pour la prévision à très courte échéance.",
    "Ablation studies show that both the height prior and the station data are needed.",
    "Compared with interpolation, the error falls by a third in the lowest kilometre.",
    "Limitations remain for convective cells that form entirely inside the blind zone.",
]


def sample_passages(count: int = 48) -> list[str]:
    passages = []
    for n in range(count):
        sentences = [_SENTENCES[(n * 5 + i * 7) % len(_SENTENCES)] for i in range(18)]
        passages.append(f"Section {n + 1}. " + " ".join(sentences))
    return passages
