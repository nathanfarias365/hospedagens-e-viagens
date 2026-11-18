"""
Aplicação web demonstrativa de reservas de hospedagem.

Este módulo reúne:
- os modelos dos dados;
- as regras de validação e disponibilidade;
- o acesso ao banco SQLite;
- a API HTTP e a entrega dos arquivos estáticos.
"""

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


# ---------------------------------------------------------------------------
# Configuração geral
# ---------------------------------------------------------------------------

ROOT = Path(__file__).resolve().parent
DATABASE_PATH = ROOT / "reservas.db"

CONFIRMED_STATUS = "confirmada"
MIN_GUESTS = 1
MAX_GUESTS = 20
MIN_STAY_NIGHTS = 1
MAX_STAY_NIGHTS = 90
MAX_REQUEST_SIZE = 100_000


# ---------------------------------------------------------------------------
# Exceções da aplicação
# ---------------------------------------------------------------------------


class BookingError(Exception):
    """Exceção base para erros previsíveis do fluxo de reserva."""


class ValidationError(BookingError):
    """Indica que os dados enviados pelo cliente são inválidos."""


class AvailabilityError(BookingError):
    """Indica que não existe quarto disponível para a solicitação."""


# ---------------------------------------------------------------------------
# Hierarquia de tipos de quarto
# ---------------------------------------------------------------------------


class Room(ABC):
    """Contrato comum para todos os tipos de quarto."""

    room_type: str
    capacity: int
    nightly_rate: float

    @abstractmethod
    def price_for(self, nights: int) -> float:
        """Calcula o preço total da estadia."""


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
        # A suíte possui 5% de acréscimo sobre o valor da estadia.
        return self.nightly_rate * nights * 1.05


# Mapeia o nome exibido no sistema para a classe responsável pelo cálculo.
ROOM_TYPES: dict[str, type[Room]] = {
    room.room_type: room
    for room in (SingleRoom, DoubleRoom, Suite)
}


# ---------------------------------------------------------------------------
# Modelos de dados
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Customer:
    """Dados cadastrais de um cliente."""

    name: str
    document: str
    email: str
    phone: str

    @classmethod
    def from_payload(cls, payload: dict) -> Customer:
        """Valida e transforma os dados recebidos em um cliente."""
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
    """Representação completa de uma hospedagem."""

    hotel_id: str
    name: str
    country: str
    city: str
    category: str
    description: str


@dataclass(frozen=True)
class Reservation:
    """Dados retornados após a criação de uma reserva."""

    code: str
    hotel_name: str
    room_type: str
    checkin: str
    checkout: str
    guests: int
    total_price: float


# Dados iniciais usados quando o banco é criado pela primeira vez.
HOTELS = (
    Hotel("rio", "Hotel Vista da Baía", "Brasil", "Rio de Janeiro", "Hotel",
          "Quartos para famílias perto da orla e áreas de convivência."),
    Hotel("lisboa", "Casa do Miradouro", "Portugal", "Lisboa", "Apartamento",
          "Sala acolhedora e espaço para compartilhar dias na cidade."),
    Hotel("orlando", "Jardins de Orlando", "Estados Unidos", "Orlando", "Resort",
          "Piscina e espaços de convivência para viajar em grupo."),
    Hotel("fortaleza", "Vila Brisa do Mar", "Brasil", "Fortaleza", "Vila",
          "Casa com jardim e espaço para reunir toda a turma."),
    Hotel("sao-paulo", "Hotel Alameda", "Brasil", "São Paulo", "Hotel",
          "Quartos confortáveis como ponto de partida para explorar a cidade."),
    Hotel("belem", "Chalé Jardim Amazônico", "Brasil", "Belém", "Chalé",
          "Um refúgio arborizado para desacelerar durante a viagem."),
)


# ---------------------------------------------------------------------------
# Utilidades de validação
# ---------------------------------------------------------------------------


def parse_date(value: object, label: str) -> date:
    """Converte uma data no formato ISO AAAA-MM-DD."""
    try:
        return date.fromisoformat(str(value))
    except (TypeError, ValueError) as error:
        raise ValidationError(
            f"A data de {label} deve estar no formato AAAA-MM-DD."
        ) from error


def parse_guest_count(value: object) -> int:
    """Converte e valida a quantidade de hóspedes."""
    try:
        guests = int(value)
    except (ValueError, TypeError) as error:
        raise ValidationError(
            "A quantidade de hóspedes deve ser um número."
        ) from error

    if not MIN_GUESTS <= guests <= MAX_GUESTS:
        raise ValidationError(
            f"A quantidade de hóspedes deve estar entre "
            f"{MIN_GUESTS} e {MAX_GUESTS}."
        )
    return guests


# ---------------------------------------------------------------------------
# Regras de negócio e persistência
# ---------------------------------------------------------------------------


class BookingService:
    """Centraliza validações, consultas e gravações no banco SQLite."""

    def __init__(self, database_path: Path = DATABASE_PATH):
        self.database_path = Path(database_path)
        self.initialize()

    def connect(self) -> sqlite3.Connection:
        """Abre uma conexão configurada com chaves estrangeiras ativadas."""
        connection = sqlite3.connect(self.database_path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    @contextmanager
    def connection(self):
        """Garante commit ou rollback e fecha a conexão ao sair do bloco."""
        connection = self.connect()
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def initialize(self) -> None:
        """Cria as tabelas e insere os hotéis e quartos iniciais."""
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

            hotel_count = connection.execute(
                "SELECT COUNT(*) FROM hotels"
            ).fetchone()[0]
            if hotel_count == 0:
                self._seed(connection)

    @staticmethod
    def _seed(connection: sqlite3.Connection) -> None:
        """Popula o banco vazio com os dados iniciais da demonstração."""
        connection.executemany(
            """
            INSERT INTO hotels
                (id, name, country, city, category, description)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    hotel.hotel_id,
                    hotel.name,
                    hotel.country,
                    hotel.city,
                    hotel.category,
                    hotel.description,
                )
                for hotel in HOTELS
            ],
        )

        # Cada hotel começa com duas unidades de cada tipo de quarto.
        for hotel in HOTELS:
            for room_type in ROOM_TYPES.values():
                room = room_type()
                for _ in range(2):
                    connection.execute(
                        """
                        INSERT INTO rooms
                            (hotel_id, room_type, capacity, nightly_rate)
                        VALUES (?, ?, ?, ?)
                        """,
                        (
                            hotel.hotel_id,
                            room.room_type,
                            room.capacity,
                            room.nightly_rate,
                        ),
                    )

    @staticmethod
    def _validate_stay(
        checkin_value: object,
        checkout_value: object,
    ) -> tuple[date, date, int]:
        """Valida datas e calcula a quantidade de noites."""
        checkin = parse_date(checkin_value, "check-in")
        checkout = parse_date(checkout_value, "check-out")
        nights = (checkout - checkin).days

        if checkin < date.today():
            raise ValidationError("O check-in não pode ser anterior a hoje.")

        if not MIN_STAY_NIGHTS <= nights <= MAX_STAY_NIGHTS:
            raise ValidationError(
                f"A estadia deve ter entre "
                f"{MIN_STAY_NIGHTS} e {MAX_STAY_NIGHTS} noites."
            )

        return checkin, checkout, nights

    def add_customer(self, payload: dict) -> dict:
        """Cadastra um cliente ou atualiza seus dados pelo documento."""
        customer = Customer.from_payload(payload)

        with self.connection() as connection:
            connection.execute(
                """
                INSERT INTO customers (name, document, email, phone)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(document) DO UPDATE SET
                    name = excluded.name,
                    email = excluded.email,
                    phone = excluded.phone
                """,
                (
                    customer.name,
                    customer.document,
                    customer.email,
                    customer.phone,
                ),
            )
            row = connection.execute(
                """
                SELECT id, name, document, email, phone
                FROM customers
                WHERE document = ?
                """,
                (customer.document,),
            ).fetchone()

        return dict(row)

    def add_room(self, payload: dict) -> dict:
        """Adiciona uma unidade de quarto a um hotel existente."""
        hotel_id = str(payload.get("hotel_id", "")).strip()
        room_name = str(payload.get("room_type", "")).strip()
        room_class = ROOM_TYPES.get(room_name)

        if room_class is None:
            raise ValidationError(
                "Tipo de quarto inválido. Use Solteiro, Casal ou Suíte."
            )

        with self.connection() as connection:
            hotel = connection.execute(
                "SELECT 1 FROM hotels WHERE id = ?",
                (hotel_id,),
            ).fetchone()
            if hotel is None:
                raise ValidationError("Hotel não encontrado.")

            room = room_class()
            cursor = connection.execute(
                """
                INSERT INTO rooms
                    (hotel_id, room_type, capacity, nightly_rate)
                VALUES (?, ?, ?, ?)
                """,
                (
                    hotel_id,
                    room.room_type,
                    room.capacity,
                    room.nightly_rate,
                ),
            )

        return {
            "id": cursor.lastrowid,
            "hotel_id": hotel_id,
            "room_type": room_name,
        }

    @staticmethod
    def _matches_hotel_filters(hotel: sqlite3.Row, filters: dict[str, str]) -> bool:
        """Verifica os filtros opcionais de país, cidade e categoria."""
        if filters.get("country") and hotel["country"] != filters["country"]:
            return False
        if filters.get("city") and hotel["city"] != filters["city"]:
            return False
        if (
            filters.get("category")
            and filters["category"] != "Todos"
            and hotel["category"] != filters["category"]
        ):
            return False
        return True

    def list_hotels(self, filters: dict[str, str]) -> list[dict]:
        """Lista hotéis e, quando informado, calcula os quartos disponíveis."""
        with self.connection() as connection:
            hotel_rows = connection.execute(
                "SELECT * FROM hotels ORDER BY name"
            ).fetchall()

            # A disponibilidade só é consultada quando o período foi informado.
            should_check_availability = (
                bool(filters.get("checkin"))
                or bool(filters.get("checkout"))
            )

            if should_check_availability:
                checkin, checkout, _ = self._validate_stay(
                    filters.get("checkin"),
                    filters.get("checkout"),
                )
                guests = parse_guest_count(filters.get("guests", "1"))
            else:
                checkin = checkout = guests = None

            results = []
            for hotel in hotel_rows:
                if not self._matches_hotel_filters(hotel, filters):
                    continue

                available_rooms = []
                if should_check_availability:
                    room_rows = connection.execute(
                        """
                        SELECT
                            r.room_type,
                            COUNT(*) AS available,
                            MIN(r.nightly_rate) AS nightly_rate
                        FROM rooms r
                        WHERE r.hotel_id = ? AND r.capacity >= ?
                        AND NOT EXISTS (
                            SELECT 1
                            FROM reservations b
                            WHERE b.room_id = r.id
                              AND b.status = ?
                              AND b.checkin < ?
                              AND b.checkout > ?
                        )
                        GROUP BY r.room_type
                        ORDER BY r.room_type
                        """,
                        (
                            hotel["id"],
                            guests,
                            CONFIRMED_STATUS,
                            checkout.isoformat(),
                            checkin.isoformat(),
                        ),
                    ).fetchall()

                    available_rooms = [
                        {
                            "room_type": row["room_type"],
                            "available": row["available"],
                            "nightly_rate": row["nightly_rate"],
                        }
                        for row in room_rows
                    ]

                results.append({
                    **dict(hotel),
                    "available_rooms": available_rooms,
                })

        return results

    def create_reservation(self, payload: dict) -> dict:
        """Valida os dados, seleciona um quarto livre e cria a reserva."""
        customer = Customer.from_payload(payload)
        checkin, checkout, nights = self._validate_stay(
            payload.get("checkin"),
            payload.get("checkout"),
        )
        guests = parse_guest_count(payload.get("guests", 0))

        hotel_id = str(payload.get("hotel_id", "")).strip()
        room_name = str(payload.get("room_type", "")).strip()
        room_class = ROOM_TYPES.get(room_name)
        if room_class is None:
            raise ValidationError("Selecione um tipo de acomodação válido.")

        with self.connection() as connection:
            # BEGIN IMMEDIATE impede que duas requisições reservem o mesmo quarto.
            connection.execute("BEGIN IMMEDIATE")

            hotel = connection.execute(
                "SELECT name FROM hotels WHERE id = ?",
                (hotel_id,),
            ).fetchone()
            if hotel is None:
                raise ValidationError("Hotel não encontrado.")

            room = connection.execute(
                """
                SELECT r.id
                FROM rooms r
                WHERE r.hotel_id = ?
                  AND r.room_type = ?
                  AND r.capacity >= ?
                  AND NOT EXISTS (
                      SELECT 1
                      FROM reservations b
                      WHERE b.room_id = r.id
                        AND b.status = ?
                        AND b.checkin < ?
                        AND b.checkout > ?
                  )
                ORDER BY r.id
                LIMIT 1
                """,
                (
                    hotel_id,
                    room_name,
                    guests,
                    CONFIRMED_STATUS,
                    checkout.isoformat(),
                    checkin.isoformat(),
                ),
            ).fetchone()

            if room is None:
                raise AvailabilityError(
                    "Não há quartos desse tipo disponíveis para as datas "
                    "e hóspedes informados."
                )

            # Insere o cliente ou atualiza seus dados pelo documento.
            connection.execute(
                """
                INSERT INTO customers (name, document, email, phone)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(document) DO UPDATE SET
                    name = excluded.name,
                    email = excluded.email,
                    phone = excluded.phone
                """,
                (
                    customer.name,
                    customer.document,
                    customer.email,
                    customer.phone,
                ),
            )
            customer_row = connection.execute(
                "SELECT id FROM customers WHERE document = ?",
                (customer.document,),
            ).fetchone()

            code = "RF-" + uuid.uuid4().hex[:8].upper()
            total_price = room_class().price_for(nights)

            connection.execute(
                """
                INSERT INTO reservations
                    (code, customer_id, room_id, checkin, checkout,
                     guests, total_price)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    code,
                    customer_row["id"],
                    room["id"],
                    checkin.isoformat(),
                    checkout.isoformat(),
                    guests,
                    total_price,
                ),
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


# Instância global preguiçosa usada pelas rotas HTTP.
service: BookingService | None = None


def get_service() -> BookingService:
    """Cria o serviço uma única vez e o reutiliza nas próximas requisições."""
    global service
    if service is None:
        service = BookingService()
    return service


# ---------------------------------------------------------------------------
# Servidor HTTP e rotas
# ---------------------------------------------------------------------------


class RequestHandler(BaseHTTPRequestHandler):
    """Processa requisições da API e entrega os arquivos do site."""

    server_version = "ReservaFacinho/1.0"

    def send_json(self, status: int, data: dict | list) -> None:
        """Envia uma resposta JSON com codificação UTF-8."""
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")

        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def read_json(self) -> dict:
        """Lê o corpo da requisição e valida se é um objeto JSON."""
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError as error:
            raise ValidationError("Tamanho de requisição inválido.") from error

        if length < 1 or length > MAX_REQUEST_SIZE:
            raise ValidationError(
                f"Envie um corpo JSON de até {MAX_REQUEST_SIZE // 1000} KB."
            )

        try:
            payload = json.loads(
                self.rfile.read(length).decode("utf-8")
            )
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ValidationError(
                "O corpo da requisição deve ser um JSON válido."
            ) from error

        if not isinstance(payload, dict):
            raise ValidationError("O corpo JSON deve ser um objeto.")
        return payload

    def do_GET(self) -> None:
        """Atende às consultas de estado, hotéis e arquivos estáticos."""
        parsed = urlparse(self.path)

        if parsed.path == "/api/health":
            self.send_json(200, {"status": "ok"})
            return

        if parsed.path == "/api/hotels":
            filters = {
                key: values[0]
                for key, values in parse_qs(parsed.query).items()
                if values
            }
            try:
                hotels = get_service().list_hotels(filters)
                self.send_json(200, hotels)
            except BookingError as error:
                self.send_json(400, {"error": str(error)})
            return

        self.serve_static(parsed.path)

    def do_POST(self) -> None:
        """Atende ao cadastro de clientes, quartos e reservas."""
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
            status = 409 if isinstance(error, AvailabilityError) else 400
            self.send_json(status, {"error": str(error)})

    def serve_static(self, requested_path: str) -> None:
        """Entrega arquivos do site sem permitir acesso fora da raiz."""
        path = unquote(requested_path)
        if path == "/":
            path = "/index.html"

        resolved = (ROOT / path.lstrip("/")).resolve()
        if ROOT not in resolved.parents or not resolved.is_file():
            self.send_error(404, "Arquivo não encontrado.")
            return

        content = resolved.read_bytes()
        content_type = (
            mimetypes.guess_type(str(resolved))[0]
            or "application/octet-stream"
        )

        self.send_response(200)
        self.send_header(
            "Content-Type",
            f"{content_type}; charset=utf-8",
        )
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def log_message(self, format_string: str, *args: object) -> None:
        """Mantém o padrão de log do servidor em uma única linha."""
        print(f"{self.address_string()} - {format_string % args}")


# ---------------------------------------------------------------------------
# Inicialização do servidor
# ---------------------------------------------------------------------------


if __name__ == "__main__":
    address = ("127.0.0.1", 8000)
    service = BookingService()
    print(
        f"ReservaFacinho disponível em "
        f"http://{address[0]}:{address[1]}"
    )
    ThreadingHTTPServer(address, RequestHandler).serve_forever()
