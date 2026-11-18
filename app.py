"""Servidor e regras do sistema demonstrativo de reservas de hospedagem."""

from __future__ import annotations

import json
import mimetypes
import re
import sqlite3
import uuid
from abc import ABC, abstractmethod
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import date
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse


ROOT = Path(__file__).resolve().parent
DATABASE_PATH = ROOT / "reservas.db"


class BookingError(Exception):
    """Erro esperado nas operações de reserva."""


class ValidationError(BookingError):
    """Dados enviados pelo cliente são inválidos."""


class AvailabilityError(BookingError):
    """Não existe quarto disponível para a solicitação."""


class Room(ABC):
    room_type: str
    capacity: int
    nightly_rate: float

    @abstractmethod
    def price_for(self, nights: int) -> float:
        """Calcula o preço da estadia de acordo com o tipo de quarto."""


class SingleRoom(Room):
    room_type = "Solteiro"
    capacity = 1
    nightly_rate = 180.0

    def price_for(self, nights: int) -> float:
        return self.nightly_rate * nights


class DoubleRoom(Room):
    room_type = "Casal"
    capacity = 2
    nightly_rate = 280.0

    def price_for(self, nights: int) -> float:
        return self.nightly_rate * nights


class Suite(Room):
    room_type = "Suíte"
    capacity = 4
    nightly_rate = 480.0

    def price_for(self, nights: int) -> float:
        return self.nightly_rate * nights * 1.05


ROOM_TYPES: dict[str, type[Room]] = {
    room.room_type: room for room in (SingleRoom, DoubleRoom, Suite)
}


@dataclass(frozen=True)
class Customer:
    name: str
    document: str
    email: str
    phone: str

    @classmethod
    def from_payload(cls, payload: dict) -> Customer:
        name = str(payload.get("name", "")).strip()
        document = str(payload.get("document", "")).strip()
        email = str(payload.get("email", "")).strip()
        phone = str(payload.get("phone", "")).strip()
        if not name or len(document) < 5 or "@" not in email:
            raise ValidationError("Informe nome, documento válido e e-mail.")
        if len(re.sub(r"\D", "", phone)) < 8:
            raise ValidationError("Informe um telefone com ao menos 8 dígitos.")
        return cls(name, document, email, phone)


@dataclass(frozen=True)
class Hotel:
    hotel_id: str
    name: str
    country: str
    city: str
    category: str
    description: str


@dataclass(frozen=True)
class Reservation:
    code: str
    hotel_name: str
    room_type: str
    checkin: str
    checkout: str
    guests: int
    total_price: float


HOTELS = (
    Hotel("rio", "Hotel Vista da Baía", "Brasil", "Rio de Janeiro", "Hotel", "Quartos para famílias perto da orla e áreas de convivência."),
    Hotel("lisboa", "Casa do Miradouro", "Portugal", "Lisboa", "Apartamento", "Sala acolhedora e espaço para compartilhar dias na cidade."),
    Hotel("orlando", "Jardins de Orlando", "Estados Unidos", "Orlando", "Resort", "Piscina e espaços de convivência para viajar em grupo."),
    Hotel("fortaleza", "Vila Brisa do Mar", "Brasil", "Fortaleza", "Vila", "Casa com jardim e espaço para reunir toda a turma."),
    Hotel("sao-paulo", "Hotel Alameda", "Brasil", "São Paulo", "Hotel", "Quartos confortáveis como ponto de partida para explorar a cidade."),
    Hotel("belem", "Chalé Jardim Amazônico", "Brasil", "Belém", "Chalé", "Um refúgio arborizado para desacelerar durante a viagem."),
)


def parse_date(value: object, label: str) -> date:
    try:
        parsed = date.fromisoformat(str(value))
    except (TypeError, ValueError) as error:
        raise ValidationError(f"A data de {label} deve estar no formato AAAA-MM-DD.") from error
    return parsed


class BookingService:
    def __init__(self, database_path: Path = DATABASE_PATH):
        self.database_path = Path(database_path)
        self.initialize()

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    @contextmanager
    def connection(self):
        connection = self.connect()
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def initialize(self) -> None:
        with self.connection() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS customers (
                    id INTEGER PRIMARY KEY,
                    name TEXT NOT NULL,
                    document TEXT NOT NULL UNIQUE,
                    email TEXT NOT NULL,
                    phone TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS hotels (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    country TEXT NOT NULL,
                    city TEXT NOT NULL,
                    category TEXT NOT NULL,
                    description TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS rooms (
                    id INTEGER PRIMARY KEY,
                    hotel_id TEXT NOT NULL REFERENCES hotels(id),
                    room_type TEXT NOT NULL,
                    capacity INTEGER NOT NULL,
                    nightly_rate REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS reservations (
                    id INTEGER PRIMARY KEY,
                    code TEXT NOT NULL UNIQUE,
                    customer_id INTEGER NOT NULL REFERENCES customers(id),
                    room_id INTEGER NOT NULL REFERENCES rooms(id),
                    checkin TEXT NOT NULL,
                    checkout TEXT NOT NULL,
                    guests INTEGER NOT NULL,
                    total_price REAL NOT NULL,
                    status TEXT NOT NULL DEFAULT 'confirmada'
                );
                """
            )
            if connection.execute("SELECT COUNT(*) FROM hotels").fetchone()[0] == 0:
                self._seed(connection)

    @staticmethod
    def _seed(connection: sqlite3.Connection) -> None:
        connection.executemany(
            "INSERT INTO hotels (id, name, country, city, category, description) VALUES (?, ?, ?, ?, ?, ?)",
            [
                (hotel.hotel_id, hotel.name, hotel.country, hotel.city, hotel.category, hotel.description)
                for hotel in HOTELS
            ],
        )
        for hotel in HOTELS:
            for room_type in ROOM_TYPES.values():
                room = room_type()
                for _ in range(2):
                    connection.execute(
                        "INSERT INTO rooms (hotel_id, room_type, capacity, nightly_rate) VALUES (?, ?, ?, ?)",
                        (hotel.hotel_id, room.room_type, room.capacity, room.nightly_rate),
                    )

    @staticmethod
    def _validate_stay(checkin_value: object, checkout_value: object) -> tuple[date, date, int]:
        checkin = parse_date(checkin_value, "check-in")
        checkout = parse_date(checkout_value, "check-out")
        nights = (checkout - checkin).days
        if checkin < date.today():
            raise ValidationError("O check-in não pode ser anterior a hoje.")
        if nights < 1 or nights > 90:
            raise ValidationError("A estadia deve ter entre 1 e 90 noites.")
        return checkin, checkout, nights

    def add_customer(self, payload: dict) -> dict:
        customer = Customer.from_payload(payload)
        with self.connection() as connection:
            connection.execute(
                """INSERT INTO customers (name, document, email, phone) VALUES (?, ?, ?, ?)
                ON CONFLICT(document) DO UPDATE SET
                    name = excluded.name, email = excluded.email, phone = excluded.phone""",
                (customer.name, customer.document, customer.email, customer.phone),
            )
            row = connection.execute(
                "SELECT id, name, document, email, phone FROM customers WHERE document = ?",
                (customer.document,),
            ).fetchone()
        return dict(row)

    def add_room(self, payload: dict) -> dict:
        hotel_id = str(payload.get("hotel_id", "")).strip()
        room_name = str(payload.get("room_type", "")).strip()
        room_class = ROOM_TYPES.get(room_name)
        if room_class is None:
            raise ValidationError("Tipo de quarto inválido. Use Solteiro, Casal ou Suíte.")
        with self.connection() as connection:
            if connection.execute("SELECT 1 FROM hotels WHERE id = ?", (hotel_id,)).fetchone() is None:
                raise ValidationError("Hotel não encontrado.")
            room = room_class()
            cursor = connection.execute(
                "INSERT INTO rooms (hotel_id, room_type, capacity, nightly_rate) VALUES (?, ?, ?, ?)",
                (hotel_id, room.room_type, room.capacity, room.nightly_rate),
            )
        return {"id": cursor.lastrowid, "hotel_id": hotel_id, "room_type": room_name}

    def list_hotels(self, filters: dict[str, str]) -> list[dict]:
        with self.connection() as connection:
            hotels = connection.execute("SELECT * FROM hotels ORDER BY name").fetchall()
            results = []
            if filters.get("checkin") or filters.get("checkout"):
                checkin, checkout, _ = self._validate_stay(filters.get("checkin"), filters.get("checkout"))
                try:
                    guests = int(filters.get("guests", "1"))
                except ValueError as error:
                    raise ValidationError("A quantidade de hóspedes deve ser um número.") from error
                if guests < 1 or guests > 20:
                    raise ValidationError("A quantidade de hóspedes deve estar entre 1 e 20.")
                for hotel in hotels:
                    if filters.get("country") and hotel["country"] != filters["country"]:
                        continue
                    if filters.get("city") and hotel["city"] != filters["city"]:
                        continue
                    if filters.get("category") and filters["category"] != "Todos" and hotel["category"] != filters["category"]:
                        continue
                    room_rows = connection.execute(
                        """SELECT r.room_type, COUNT(*) AS available, MIN(r.nightly_rate) AS nightly_rate
                        FROM rooms r
                        WHERE r.hotel_id = ? AND r.capacity >= ?
                        AND NOT EXISTS (
                            SELECT 1 FROM reservations b
                            WHERE b.room_id = r.id AND b.status = 'confirmada'
                            AND b.checkin < ? AND b.checkout > ?
                        )
                        GROUP BY r.room_type ORDER BY r.room_type""",
                        (hotel["id"], guests, checkout.isoformat(), checkin.isoformat()),
                    ).fetchall()
                    available_rooms = [
                        {
                            "room_type": row["room_type"],
                            "available": row["available"],
                            "nightly_rate": row["nightly_rate"],
                        }
                        for row in room_rows
                    ]
                    results.append({**dict(hotel), "available_rooms": available_rooms})
            else:
                for hotel in hotels:
                    if filters.get("country") and hotel["country"] != filters["country"]:
                        continue
                    if filters.get("city") and hotel["city"] != filters["city"]:
                        continue
                    if filters.get("category") and filters["category"] != "Todos" and hotel["category"] != filters["category"]:
                        continue
                    results.append({**dict(hotel), "available_rooms": []})
        return results

    def create_reservation(self, payload: dict) -> dict:
        customer = Customer.from_payload(payload)
        checkin, checkout, nights = self._validate_stay(payload.get("checkin"), payload.get("checkout"))
        try:
            guests = int(payload.get("guests", 0))
        except (ValueError, TypeError) as error:
            raise ValidationError("A quantidade de hóspedes deve ser um número.") from error
        if not 1 <= guests <= 20:
            raise ValidationError("A quantidade de hóspedes deve estar entre 1 e 20.")
        hotel_id = str(payload.get("hotel_id", "")).strip()
        room_name = str(payload.get("room_type", "")).strip()
        room_class = ROOM_TYPES.get(room_name)
        if room_class is None:
            raise ValidationError("Selecione um tipo de acomodação válido.")

        with self.connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            hotel = connection.execute("SELECT name FROM hotels WHERE id = ?", (hotel_id,)).fetchone()
            if hotel is None:
                raise ValidationError("Hotel não encontrado.")
            room = connection.execute(
                """SELECT r.id FROM rooms r
                WHERE r.hotel_id = ? AND r.room_type = ? AND r.capacity >= ?
                AND NOT EXISTS (
                    SELECT 1 FROM reservations b
                    WHERE b.room_id = r.id AND b.status = 'confirmada'
                    AND b.checkin < ? AND b.checkout > ?
                )
                ORDER BY r.id LIMIT 1""",
                (hotel_id, room_name, guests, checkout.isoformat(), checkin.isoformat()),
            ).fetchone()
            if room is None:
                raise AvailabilityError("Não há quartos desse tipo disponíveis para as datas e hóspedes informados.")
            connection.execute(
                """INSERT INTO customers (name, document, email, phone) VALUES (?, ?, ?, ?)
                ON CONFLICT(document) DO UPDATE SET
                    name = excluded.name, email = excluded.email, phone = excluded.phone""",
                (customer.name, customer.document, customer.email, customer.phone),
            )
            customer_row = connection.execute(
                "SELECT id FROM customers WHERE document = ?", (customer.document,)
            ).fetchone()
            code = "RF-" + uuid.uuid4().hex[:8].upper()
            total_price = room_class().price_for(nights)
            connection.execute(
                """INSERT INTO reservations
                (code, customer_id, room_id, checkin, checkout, guests, total_price)
                VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (code, customer_row["id"], room["id"], checkin.isoformat(), checkout.isoformat(), guests, total_price),
            )
        reservation = Reservation(
            code=code,
            hotel_name=hotel["name"],
            room_type=room_name,
            checkin=checkin.isoformat(),
            checkout=checkout.isoformat(),
            guests=guests,
            total_price=round(total_price, 2),
        )
        return asdict(reservation)


service: BookingService | None = None


def get_service() -> BookingService:
    global service
    if service is None:
        service = BookingService()
    return service


class RequestHandler(BaseHTTPRequestHandler):
    server_version = "ReservaFacinho/1.0"

    def send_json(self, status: int, data: dict | list) -> None:
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def read_json(self) -> dict:
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError as error:
            raise ValidationError("Tamanho de requisição inválido.") from error
        if length < 1 or length > 100_000:
            raise ValidationError("Envie um corpo JSON de até 100 KB.")
        try:
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ValidationError("O corpo da requisição deve ser um JSON válido.") from error
        if not isinstance(payload, dict):
            raise ValidationError("O corpo JSON deve ser um objeto.")
        return payload

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/api/health":
            self.send_json(200, {"status": "ok"})
            return
        if parsed.path == "/api/hotels":
            filters = {key: values[0] for key, values in parse_qs(parsed.query).items() if values}
            try:
                self.send_json(200, get_service().list_hotels(filters))
            except BookingError as error:
                self.send_json(400, {"error": str(error)})
            return
        self.serve_static(parsed.path)

    def do_POST(self) -> None:
        try:
            payload = self.read_json()
            if self.path == "/api/customers":
                self.send_json(201, get_service().add_customer(payload))
            elif self.path == "/api/rooms":
                self.send_json(201, get_service().add_room(payload))
            elif self.path == "/api/bookings":
                self.send_json(201, get_service().create_reservation(payload))
            else:
                self.send_json(404, {"error": "Rota não encontrada."})
        except BookingError as error:
            self.send_json(409 if isinstance(error, AvailabilityError) else 400, {"error": str(error)})

    def serve_static(self, requested_path: str) -> None:
        path = unquote(requested_path)
        if path == "/":
            path = "/index.html"
        resolved = (ROOT / path.lstrip("/")).resolve()
        if ROOT not in resolved.parents or not resolved.is_file():
            self.send_error(404, "Arquivo não encontrado.")
            return
        content = resolved.read_bytes()
        content_type = mimetypes.guess_type(str(resolved))[0] or "application/octet-stream"
        self.send_response(200)
        self.send_header("Content-Type", f"{content_type}; charset=utf-8")
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def log_message(self, format_string: str, *args: object) -> None:
        print(f"{self.address_string()} - {format_string % args}")


if __name__ == "__main__":
    address = ("127.0.0.1", 8000)
    service = BookingService()
    print(f"ReservaFacinho disponível em http://{address[0]}:{address[1]}")
    ThreadingHTTPServer(address, RequestHandler).serve_forever()
