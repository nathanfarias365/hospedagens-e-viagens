# FlowReservas — reservas de hospedagem

Site responsivo para explorar destinos e realizar reservas demonstrativas. O servidor Python entrega a interface e uma API REST; os dados são persistidos em SQLite.

## Executar

Requer Python 3.10 ou superior, sem dependências externas.

```powershell
python app.py
```

Abra `http://127.0.0.1:8000`. Não abra `index.html` diretamente: a integração com a API exige que o servidor esteja ativo. O banco `reservas.db` e os hotéis/quartos iniciais são criados automaticamente.

## Funcionalidades

- Consulta de disponibilidade por destino, datas, hóspedes e categoria de hospedagem.
- Cadastro e atualização de clientes pelo documento informado na reserva.
- Reservas de quartos solteiro, casal ou suíte, com capacidade, preço por noite e total da estadia.
- Bloqueio de reservas sobrepostas; o quarto fica reservado apenas entre check-in e check-out.
- Cadastro de quartos pela API para simular a gestão do inventário.
- Outras áreas do site: mapa de destinos, página de voos ilustrativa e pesquisa de atrações.

### Rotas da API

- `GET /api/health`: estado do servidor.
- `GET /api/hotels?country=Brasil&city=Belém&checkin=AAAA-MM-DD&checkout=AAAA-MM-DD&guests=2&category=Todos`: pesquisa e disponibilidade.
- `POST /api/customers`: cria ou atualiza cliente. JSON esperado: `name`, `document`, `email`, `phone`.
- `POST /api/rooms`: cadastra um quarto. JSON esperado: `hotel_id` e `room_type` (`Solteiro`, `Casal` ou `Suíte`).
- `POST /api/bookings`: cria uma reserva com os dados do cliente, `hotel_id`, `room_type`, `checkin`, `checkout` e `guests`.

## Aplicação dos paradigmas e conceitos de programação

1. **Decisão e repetição** — `app.py`: validações condicionais nas datas, hóspedes, capacidade e disponibilidade; laços percorrem hotéis, tipos de quarto e quartos livres. `script.js`: filtros da interface e construção dos campos da reserva.
2. **Funções/subprogramas** — `app.py`: `parse_date`, `Customer.from_payload`, `BookingService.initialize`, `_validate_stay`, `add_customer`, `add_room`, `list_hotels`, `create_reservation` e métodos HTTP para servir API e arquivos. Cada função valida ou executa uma responsabilidade específica.
3. **Bibliotecas** — `datetime` valida datas e calcula noites; `sqlite3` persiste os dados; `http.server` fornece o servidor/API; `json` processa as mensagens; `dataclasses` modela os dados; `abc` define o contrato polimórfico de quartos; `contextlib` fecha corretamente conexões; `pathlib`, `urllib.parse`, `mimetypes`, `re` e `uuid` apoiam caminhos, URL, arquivos, validação de telefone e códigos de reserva. No navegador, `fetch` integra a página com a API.
4. **Exceções** — `BookingError` é a exceção base própria; `ValidationError` sinaliza dados inválidos e `AvailabilityError` indica falta de inventário. `ValueError`, `TypeError`, `UnicodeDecodeError` e `json.JSONDecodeError` são tratadas ao validar entrada e datas. Conflitos de disponibilidade retornam HTTP 409; erros de validação, HTTP 400.
5. **Classes, atributos e métodos** — `Customer` (nome, documento, e-mail, telefone e `from_payload`), `Hotel` (identificador, nome, país, cidade, categoria, descrição), `Reservation` (código, hotel, quarto, datas, hóspedes e preço), `BookingService` (acesso ao banco e regras de negócio) e `RequestHandler` (rotas HTTP). `Room` define o contrato de quarto e o cálculo `price_for`.
6. **Herança e polimorfismo** — `SingleRoom`, `DoubleRoom` e `Suite` herdam de `Room` e implementam `price_for`. O sistema seleciona a classe pelo tipo de quarto; a chamada polimórfica calcula o valor sem duplicar o fluxo de reserva. Cada tipo também define capacidade e preço por noite.

## Testes

```powershell
python -m unittest -v
```

> **Demonstração acadêmica:** o banco local guarda dados pessoais sem autenticação ou criptografia e não deve ser usado para reservas reais. Para produção, implemente controle de acesso, proteção de dados, pagamentos e implantação segura.
