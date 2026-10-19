
const API_URL = "http://127.0.0.1:8000";

const searchForm = document.getElementById("searchForm");
const searchButton = document.getElementById("searchButton");
const statusMessage = document.getElementById("statusMessage");
const profileModal = document.getElementById("profileModal");
const profileContent = document.getElementById("profileContent");
const closeModal = document.getElementById("closeModal");


// Create an element with safe text content.
function createElement(tag, className, text) {
    const element = document.createElement(tag);
    element.className = className;
    element.textContent = text ?? "Not available";
    return element;
}


// Display profile statistics.
function createStatCard(value, label) {
    const card = createElement("div", "stat-card", "");

    card.appendChild(createElement("strong", "", value));
    card.appendChild(createElement("span", "", label));

    return card;
}


// Render extracted profile information.
function displayProfile(profile) {
    profileContent.replaceChildren();

    profileContent.appendChild(
        createElement("div", "profile-name", profile.nickname)
    );

    profileContent.appendChild(
        createElement(
            "div",
            "profile-username",
            `@${profile.username}`
        )
    );

    const stats = createElement("div", "stats-grid", "");

    stats.appendChild(
        createStatCard(profile.followers, "Seguidores")
    );

    stats.appendChild(
        createStatCard(profile.following, "Seguidos")
    );

    stats.appendChild(
        createStatCard(profile.likes, "Me gusta")
    );

    profileContent.appendChild(stats);

    profileContent.appendChild(
        createElement("p", "profile-bio", profile.bio)
    );

    profileModal.showModal();
}


// Request public profile information from FastAPI.
async function searchProfile(username) {
    const response = await fetch(
        `${API_URL}/api/profile/${encodeURIComponent(username)}`
    );

    if (!response.ok) {
        let message = "No se pudo consultar el perfil.";

        try {
            const error = await response.json();
            message = error.detail || message;
        } catch {
            // Keep the default message.
        }

        throw new Error(message);
    }

    return response.json();
}


// Handle the search form.
searchForm.addEventListener("submit", async (event) => {
    event.preventDefault();

    const username = document
        .getElementById("username")
        .value
        .trim()
        .replace(/^@/, "");

    if (!username) {
        statusMessage.textContent = "Ingresa un username.";
        return;
    }

    searchButton.disabled = true;
    statusMessage.textContent = "Consultando perfil...";

    try {
        const profile = await searchProfile(username);

        displayProfile(profile);
        statusMessage.textContent = "Consulta completada.";

    } catch (error) {
        statusMessage.textContent = error.message;

    } finally {
        searchButton.disabled = false;
    }
});


// Close the profile modal.
closeModal.addEventListener("click", () => {
    profileModal.close();
});
