document.addEventListener("DOMContentLoaded", function () {

    // Sidebar toggle for mobile devices
    const navToggle = document.getElementById("navToggle");
    const appContainer = document.querySelector(".app-container");
    const sidebarOverlay = document.getElementById("sidebarOverlay");

    if (navToggle && appContainer) {
        navToggle.addEventListener("click", function () {
            appContainer.classList.toggle("sidebar-open");
        });
    }
    if (sidebarOverlay && appContainer) {
        sidebarOverlay.addEventListener("click", function () {
            appContainer.classList.remove("sidebar-open");
        });
    }

    // Rename class selector to prevent conflict with newer page-specific attendance logic
    const statusText = document.querySelector(".legacy-attendance-status");
    const checkInBtn = document.querySelector("#checkInBtn");
    const checkOutBtn = document.querySelector("#checkOutBtn");

    if (!statusText) return;

    function loadTodayStatus() {
        fetch("/hrms/attendance/today-status")
            .then(res => res.json())
            .then(data => {

                if (data.status === "Checked In") {
                    statusText.innerHTML = `
                        Checked In at ${data.time} <br>
                        Working: ${data.worked}
                    `;
                }
                else if (data.status === "Checked Out") {
                    statusText.innerHTML = `
                        Checked Out <br>
                        Worked: ${data.worked}
                    `;
                }
                else {
                    statusText.innerHTML = "Not Marked";
                }

            });
    }

    if (checkInBtn) {
        checkInBtn.addEventListener("click", function () {
            fetch("/hrms/attendance/check-in", {
                method: "POST"
            })
            .then(res => res.json())
            .then(data => {
                alert(data.message || data.error);
                loadTodayStatus();
            });
        });
    }

    if (checkOutBtn) {
        checkOutBtn.addEventListener("click", function () {
            fetch("/hrms/attendance/check-out", {
                method: "POST"
            })
            .then(res => res.json())
            .then(data => {
                alert(data.message || data.error);
                loadTodayStatus();
            });
        });
    }

    loadTodayStatus();
    setInterval(loadTodayStatus, 10000);

});
