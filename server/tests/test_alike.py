"""Papers whose titles share words: the paper a piece of code belongs to,
or the same paper without a shared identifier."""

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from tests.people import Person


def alike(person: Person, item_id: str) -> list[str]:
    response = person.get(f"/api/items/{item_id}/alike")
    assert response.status_code == 200, response.text
    return [other["title"] for other in response.json()]


def test_titles_that_share_words(client: TestClient, db: Session) -> None:
    ada, bob = Person(client, db, "ada"), Person(client, db, "bob")
    ada.add("<i>Spin</i> qubits")
    ada.add("Spin qubits in silicon")
    ada.add("Protein folding")
    ada.add("Qubits")  # one word: all of it shared
    ada.add("Spin waves and qubit readout in large superconducting arrays")
    bob.add("Spin qubits")  # bob's own: not ada's to see
    code = ada.add("Code of Spin qubits")

    # The most alike first (by Dice: shared words of both titles' words);
    # one shared word of two long titles is too little.
    assert alike(ada, code["id"]) == [
        "<i>Spin</i> qubits",
        "Spin qubits in silicon",
        "Qubits",
    ]
    assert alike(ada, ada.add("Folding of proteins")["id"]) == ["Protein folding"]
    assert alike(ada, ada.add("Nothing like the others")["id"]) == []


def test_listed_by_the_words_of_their_titles(client: TestClient, db: Session) -> None:
    ada = Person(client, db, "ada")
    for title in ("Spin qubits", "Inspiring qubit designs", "Spin waves", "A qubit"):
        ada.add(title)

    def listed(words: str) -> list[str]:
        response = ada.get("/api/items", params={"title_words": words})
        assert response.status_code == 200, response.text
        return sorted(item["title"] for item in response.json())

    # Stems ("qubits": "qubit"), whole words ("spin" is not in "inspiring").
    assert listed("qubits") == ["A qubit", "Inspiring qubit designs", "Spin qubits"]
    assert listed("spin qubit") == ["Spin qubits"]
    # Only stop words: no filter.
    assert len(listed("the of")) == 4
