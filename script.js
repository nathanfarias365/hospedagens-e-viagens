const cities = {
  Brasil: ["Belém", "Fortaleza", "Rio de Janeiro", "São Paulo"],
  Portugal: ["Lisboa"],
  "Estados Unidos": ["Orlando"],
};
const places = {
  Belém: { coords: [-1.4558, -48.4902], country: "Brasil", stay: "Chalé Jardim Amazônico" },
  Fortaleza: { coords: [-3.7319, -38.5267], country: "Brasil", stay: "Vila Brisa do Mar" },
  "Rio de Janeiro": { coords: [-22.9068, -43.1729], country: "Brasil", stay: "Hotel Vista da Baía" },
  "São Paulo": { coords: [-23.5505, -46.6333], country: "Brasil", stay: "Hotel Alameda" },
  Lisboa: { coords: [38.7223, -9.1393], country: "Portugal", stay: "Casa do Miradouro" },
  Orlando: { coords: [28.5383, -81.3792], country: "Estados Unidos", stay: "Jardins de Orlando" },
};
const roomLabels = { Solteiro: "Quarto solteiro", Casal: "Quarto casal", "Suíte": "Suíte" };
let map;
const markers = {};
let lastFocus = null;
let activeCategory = "Todas";
let staySearch = { checkin: "", checkout: "", guests: 2, country: "", city: "", category: "Todos" };
const formatPrice = (price) => Number(price).toLocaleString("pt-BR", { minimumFractionDigits: 2 });

function showPage() {
  const requested = location.hash.slice(1);
  const page = requested === "voos" || requested === "atracoes" ? requested : "hospedagens";
  document.querySelectorAll(".view").forEach((element) => { element.hidden = element.id !== page; });
  document.querySelectorAll(".nav-link").forEach((element) => {
    if (element.getAttribute("href") === `#${page}`) element.setAttribute("aria-current", "page");
    else element.removeAttribute("aria-current");
  });
  window.scrollTo(0, 0);
  if (page === "voos") setTimeout(ensureMap, 80);
}
window.addEventListener("hashchange", showPage);

function ensureMap() {
  if (map) {
    map.invalidateSize();
    return;
  }
  map = L.map("map", { scrollWheelZoom: false }).setView([-12, -48], 4);
  map.attributionControl.setPrefix(false);
  L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
    maxZoom: 19,
    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener noreferrer">OpenStreetMap</a> contributors',
  }).addTo(map);
  Object.entries(places).forEach(([city, place]) => {
    const popup = document.createElement("div");
    const heading = document.createElement("strong");
    const description = document.createElement("p");
    heading.textContent = `${city} · ${place.country}`;
    description.textContent = `Hospedagem: ${place.stay}`;
    popup.append(heading, description);
    markers[city] = L.marker(place.coords).addTo(map).bindPopup(popup);
  });
  setTimeout(() => map.invalidateSize(), 100);
}

function focusCity(city) {
  if (!places[city]) return;
  ensureMap();
  map.setView(places[city].coords, 10);
  markers[city].openPopup();
  document.getElementById("map").scrollIntoView({ behavior: "smooth", block: "center" });
}

function connectCountry(countryId, cityId) {
  const country = document.getElementById(countryId);
  const city = document.getElementById(cityId);
  country.addEventListener("change", () => {
    city.replaceChildren(new Option("Selecione uma cidade", ""));
    (cities[country.value] || []).forEach((name) => city.add(new Option(name, name)));
  });
}
connectCountry("flight-country", "flight-city");
connectCountry("stay-country", "stay-city");

function localToday() {
  const now = new Date();
  return [now.getFullYear(), String(now.getMonth() + 1).padStart(2, "0"), String(now.getDate()).padStart(2, "0")].join("-");
}
function addDays(dateString, days) {
  const [year, month, day] = dateString.split("-").map(Number);
  const date = new Date(year, month - 1, day);
  date.setDate(date.getDate() + days);
  return [date.getFullYear(), String(date.getMonth() + 1).padStart(2, "0"), String(date.getDate()).padStart(2, "0")].join("-");
}
const todayString = localToday();
const defaultCheckin = addDays(todayString, 1);
["flight-date", "stay-date"].forEach((id) => {
  const input = document.getElementById(id);
  input.min = todayString;
  if (id === "stay-date") input.value = defaultCheckin;
});

function validate(form, feedback) {
  if (!form.reportValidity()) {
    feedback.textContent = "Confira os campos obrigatórios e os limites indicados.";
    return false;
  }
  const date = form.querySelector('input[type="date"]');
  if (date && date.value < todayString) {
    feedback.textContent = "Escolha uma data de hoje ou posterior.";
    date.focus();
    return false;
  }
  return true;
}

document.getElementById("flight-form").addEventListener("submit", (event) => {
  event.preventDefault();
  const feedback = document.getElementById("flight-feedback");
  if (!validate(event.currentTarget, feedback)) return;
  const city = document.getElementById("flight-city").value;
  document.getElementById("flight-empty").hidden = true;
  feedback.textContent = `Destino selecionado: ${city}. Veja a localização no mapa. Horários e passagens não são consultados em tempo real.`;
  focusCity(city);
});
document.querySelectorAll("[data-place]").forEach((button) => button.addEventListener("click", () => focusCity(button.dataset.place)));

document.querySelectorAll(".discovery-filter").forEach((button) => {
  button.addEventListener("click", () => {
    const category = button.dataset.featureCategory;
    document.querySelectorAll(".discovery-filter").forEach((item) => {
      const active = item === button;
      item.classList.toggle("active", active);
      item.setAttribute("aria-pressed", String(active));
    });
    document.querySelectorAll(".discovery-card").forEach((card) => {
      card.hidden = category !== "Todas" && card.dataset.featureCategory !== category;
    });
  });
});

document.querySelectorAll("[data-feature-link]").forEach((button) => {
  button.addEventListener("click", () => {
    const card = button.closest(".discovery-card");
    const country = document.getElementById("stay-country");
    const city = document.getElementById("stay-city");
    country.value = card.dataset.featureCountry;
    country.dispatchEvent(new Event("change"));
    city.value = card.dataset.featureCity;
    document.getElementById("stay-form").requestSubmit();
  });
});

function stayDates() {
  const checkin = document.getElementById("stay-date").value;
  const nights = Number(document.getElementById("stay-days").value);
  if (!Number.isInteger(nights) || nights < 1 || nights > 90) throw new Error("Informe de 1 a 90 noites.");
  return { checkin, checkout: addDays(checkin, nights), guests: Number(document.getElementById("stay-people").value) };
}

async function requestJson(url, options) {
  let response;
  try {
    response = await fetch(url, options);
  } catch (error) {
    throw new Error("Não foi possível conectar ao sistema. Inicie o servidor com python app.py.");
  }
  let data;
  try {
    data = await response.json();
  } catch (error) {
    throw new Error("O servidor retornou uma resposta inválida.");
  }
  if (!response.ok) throw new Error(data.error || "A solicitação não pôde ser concluída.");
  return data;
}

function resetStayCards() {
  document.querySelectorAll(".stay-card").forEach((card) => { card.hidden = false; });
  document.getElementById("stay-empty").hidden = true;
}

document.getElementById("stay-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const feedback = document.getElementById("stay-feedback");
  if (!validate(event.currentTarget, feedback)) return;
  let dates;
  try {
    dates = stayDates();
  } catch (error) {
    feedback.textContent = error.message;
    return;
  }
  staySearch = {
    ...dates,
    country: document.getElementById("stay-country").value,
    city: document.getElementById("stay-city").value,
    category: document.getElementById("stay-type").value,
  };
  const params = new URLSearchParams({
    ...staySearch,
  });
  feedback.textContent = "Consultando disponibilidade...";
  try {
    const hotels = await requestJson(`/api/hotels?${params}`);
    const byId = new Map(hotels.map((hotel) => [hotel.id, hotel]));
    let visible = 0;
    document.querySelectorAll(".stay-card").forEach((card) => {
      const hotel = byId.get(card.dataset.hotelId);
      const hasAvailability = hotel && hotel.available_rooms.length > 0;
      card.hidden = !hasAvailability;
      if (hasAvailability) {
        visible += 1;
        const summary = hotel.available_rooms
          .map((room) => `${room.available} ${roomLabels[room.room_type] || room.room_type} · R$ ${formatPrice(room.nightly_rate)}/noite`)
          .join(" · ");
        let availability = card.querySelector(".booking-meta");
        if (!availability) {
          availability = document.createElement("p");
          availability.className = "booking-meta my-3 font-semibold";
          card.querySelector(".p-5").insertBefore(availability, card.querySelector("[data-availability]"));
        }
        availability.textContent = `Disponível: ${summary}`;
        card.querySelector("[data-availability]").dataset.rooms = JSON.stringify(hotel.available_rooms);
      }
    });
    document.getElementById("stay-empty").hidden = visible > 0;
    feedback.textContent = visible
      ? `${visible} hospedagem(ns) com disponibilidade em ${staySearch.city}.`
      : "Não há quartos disponíveis para os filtros e datas escolhidos.";
  } catch (error) {
    resetStayCards();
    feedback.textContent = error.message;
  }
  document.getElementById("stay-list").scrollIntoView({ behavior: "smooth", block: "start" });
});

function openModal(modal, trigger) {
  lastFocus = trigger;
  modal.hidden = false;
  modal.querySelector("[data-close-modal]").focus();
}
function closeModal(modal) {
  modal.hidden = true;
  if (lastFocus && document.contains(lastFocus)) lastFocus.focus();
}

async function prepareBooking(button) {
  const card = button.closest(".stay-card");
  const feedback = document.getElementById("stay-feedback");
  let dates;
  try {
    dates = stayDates();
    if (document.getElementById("stay-country").value === "") {
      dates.checkin = defaultCheckin;
      dates.checkout = addDays(defaultCheckin, 4);
      dates.guests = 2;
    }
    const hotels = await requestJson(`/api/hotels?${new URLSearchParams({
      hotel_id: card.dataset.hotelId,
      country: card.dataset.country,
      city: card.dataset.city,
      checkin: dates.checkin,
      checkout: dates.checkout,
      guests: String(dates.guests),
    })}`);
    const hotel = hotels.find((item) => item.id === card.dataset.hotelId);
    if (!hotel || hotel.available_rooms.length === 0) {
      throw new Error("Não há quartos disponíveis para essas datas e quantidade de hóspedes.");
    }
    const form = document.getElementById("booking-form");
    form.reset();
    const submitButton = form.querySelector('[type="submit"]');
    submitButton.disabled = false;
    submitButton.textContent = "Confirmar reserva";
    document.getElementById("booking-hotel-id").value = hotel.id;
    document.getElementById("booking-hotel-name").textContent = `${hotel.name} · ${dates.checkin} a ${dates.checkout} · ${dates.guests} hóspede(s)`;
    document.getElementById("booking-checkin").value = dates.checkin;
    document.getElementById("booking-checkout").value = dates.checkout;
    document.getElementById("booking-guests").value = dates.guests;
    const roomType = document.getElementById("booking-room-type");
    document.getElementById("booking-feedback").textContent = "";
    roomType.replaceChildren(...hotel.available_rooms.map((room) => new Option(
      `${roomLabels[room.room_type] || room.room_type} · ${room.available} disponível(is) · R$ ${formatPrice(room.nightly_rate)}/noite`,
      room.room_type,
    )));
    openModal(document.getElementById("availability-modal"), button);
  } catch (error) {
    feedback.textContent = error.message;
  }
}
document.querySelectorAll("[data-availability]").forEach((button) => {
  button.addEventListener("click", () => prepareBooking(button));
});

document.getElementById("booking-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  const feedback = document.getElementById("booking-feedback");
  if (!form.reportValidity()) return;
  const payload = {
    hotel_id: document.getElementById("booking-hotel-id").value,
    checkin: document.getElementById("booking-checkin").value,
    checkout: document.getElementById("booking-checkout").value,
    guests: Number(document.getElementById("booking-guests").value),
    room_type: document.getElementById("booking-room-type").value,
    name: document.getElementById("booking-name").value,
    document: document.getElementById("booking-document").value,
    email: document.getElementById("booking-email").value,
    phone: document.getElementById("booking-phone").value,
  };
  feedback.textContent = "Confirmando sua reserva...";
  try {
    const booking = await requestJson("/api/bookings", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    feedback.textContent = `Reserva confirmada! Código ${booking.code} · Total R$ ${booking.total_price.toFixed(2).replace(".", ",")}.`;
    form.querySelector('[type="submit"]').textContent = "Reserva confirmada";
    form.querySelector('[type="submit"]').disabled = true;
  } catch (error) {
    feedback.textContent = error.message;
  }
});

const search = document.getElementById("attraction-search");
function filterAttractions() {
  const term = search.value.trim().toLocaleLowerCase("pt-BR");
  let count = 0;
  document.querySelectorAll(".attraction-card").forEach((card) => {
    card.hidden = !(activeCategory === "Todas" || card.dataset.category === activeCategory)
      || !card.dataset.search.includes(term);
    if (!card.hidden) count += 1;
  });
  document.getElementById("attraction-empty").hidden = count > 0;
}
search.addEventListener("input", filterAttractions);
document.querySelectorAll("[data-category]").forEach((button) => button.addEventListener("click", () => {
  activeCategory = button.dataset.category;
  document.querySelectorAll("[data-category]").forEach((item) => item.setAttribute("aria-pressed", String(item === button)));
  filterAttractions();
}));

document.querySelectorAll("[data-open-account]").forEach((button) => {
  button.addEventListener("click", () => openModal(document.getElementById("account-modal"), button));
});
document.querySelectorAll("[data-detail]").forEach((button) => button.addEventListener("click", () => {
  const card = button.closest(".attraction-card");
  document.getElementById("detail-title").textContent = card.querySelector("h3").textContent;
  document.getElementById("detail-category").textContent = card.dataset.category;
  document.getElementById("detail-city").textContent = card.querySelector('[data-template-id$="-city"]').textContent;
  document.getElementById("detail-description").textContent = card.querySelector('[data-template-id$="-desc"]').textContent;
  openModal(document.getElementById("detail-modal"), button);
}));
document.querySelectorAll(".modal").forEach((modal) => {
  modal.querySelector("[data-close-modal]").addEventListener("click", () => closeModal(modal));
  modal.addEventListener("click", (event) => { if (event.target === modal) closeModal(modal); });
  modal.addEventListener("keydown", (event) => {
    if (event.key === "Tab") {
      const focusable = [...modal.querySelectorAll('button:not([disabled]), input:not([disabled]), select:not([disabled])')]
        .filter((element) => element.offsetParent !== null);
      if (!focusable.length) return;
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    }
  });
});
document.addEventListener("keydown", (event) => {
  if (event.key === "Escape") {
    const modal = document.querySelector(".modal:not([hidden])");
    if (modal) closeModal(modal);
  }
});
showPage();
