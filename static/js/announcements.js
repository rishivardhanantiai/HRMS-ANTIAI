document.addEventListener("DOMContentLoaded", function () {

    const form = document.getElementById("composeForm");

    const templateSelect = document.getElementById("templateSelect");
    const clearTemplate = document.getElementById("clearTemplate");

    const sendToAll = document.getElementById("sendToAll");

    const recipientGroups =
        document.getElementById("recipientGroups");

    const subjectInp =
        document.getElementById("subject");

    const bodyInp =
        document.getElementById("bodyHtml");

    const departmentSelect =
        document.getElementById("departmentSelect");

    const singleEmail =
        document.getElementById("singleEmail");

    const customEmails =
        document.getElementById("customEmails");

    const audienceStatus =
        document.getElementById("audienceStatus");

    const audienceSummaryTitle =
        document.getElementById("audienceSummaryTitle");

    const audienceSummaryDescription =
        document.getElementById("audienceSummaryDescription");

    const recipientCount =
        document.getElementById("recipientCount");

    const characterCount =
        document.getElementById("characterCount");

    const previewSubject =
        document.getElementById("previewSubject");

    const previewBody =
        document.getElementById("previewBody");

    const sendStateTitle =
        document.getElementById("sendStateTitle");

    const sendStateDescription =
        document.getElementById("sendStateDescription");

    const previewBtn =
        document.getElementById("previewBtn");

    const sendBtn =
        document.getElementById("sendBtn");


    /* =====================================================
       CHOICES
    ===================================================== */

    const deptChoices = new Choices(
        departmentSelect,
        {
            removeItemButton: true,
            searchEnabled: true,
            searchPlaceholderValue:
                "Search departments...",
            placeholder: true,
            placeholderValue:
                "Select departments",
            shouldSort: false
        }
    );


    const empChoices = new Choices(
        singleEmail,
        {
            removeItemButton: true,
            searchEnabled: true,
            searchPlaceholderValue:
                "Search employees...",
            placeholder: true,
            placeholderValue:
                "Select employees",
            shouldSort: false
        }
    );


    /* =====================================================
       HELPERS
    ===================================================== */

    function getCustomEmails() {

        return customEmails.value
            .split(/[\s,;]+/)
            .map(x => x.trim())
            .filter(Boolean);

    }


    function getSelectedEmployeeEmails() {

        return empChoices
            .getValue(true)
            .filter(Boolean);

    }


    function getSelectedDepartments() {
        // Need to sum the data-recipient-count of selected options
        let count = 0;
        const options = Array.from(departmentSelect.selectedOptions);
        options.forEach(opt => {
            count += parseInt(opt.getAttribute('data-recipient-count') || 0, 10);
        });
        return count;
    }
    
    function getSelectedDepartmentNames() {
        return deptChoices
            .getValue(true)
            .filter(Boolean);
    }


    function isBulkSend(count) {

        return (
            sendToAll.checked ||
            getSelectedDepartmentNames().length > 0 ||
            count > 1
        );

    }


    const cfg = window.ANNOUNCEMENT_CONFIG || {};
    const ACTIVE_COUNT = cfg.activeCount || 0;

    function calculateRecipientCount() {

        if (sendToAll.checked) {

            return ACTIVE_COUNT;

        }

        const employees =
            getSelectedEmployeeEmails().length;

        const custom =
            getCustomEmails().length;

        /*
         * Now department totals are calculated precisely!
         */
        const departments =
            getSelectedDepartments();

        return employees + custom + departments;

    }


    function updateAudience() {

        const employees =
            getSelectedEmployeeEmails().length;

        const departments =
            getSelectedDepartmentNames().length;
            
        const departmentRecipients = getSelectedDepartments();

        const custom =
            getCustomEmails().length;


        if (sendToAll.checked) {

            recipientCount.textContent =
                ACTIVE_COUNT.toString();

            audienceStatus.textContent =
                ACTIVE_COUNT + " active employees";

            audienceSummaryTitle.textContent =
                "Everyone active";

            audienceSummaryDescription.textContent =
                "The announcement will be sent to every active employee.";

            sendStateTitle.textContent =
                "Company-wide announcement";

            sendStateDescription.textContent =
                "This is a bulk send and will require Admin approval.";

            return;
        }


        const count =
            employees + custom + departmentRecipients;


        if (!departments && !employees && !custom) {

            recipientCount.textContent = "0";

            audienceStatus.textContent =
                "No recipients selected";

            audienceSummaryTitle.textContent =
                "Choose your audience";

            audienceSummaryDescription.textContent =
                "Recipients will appear here as you select them.";

            sendStateTitle.textContent =
                "Ready to compose";

            sendStateDescription.textContent =
                "Select at least one recipient.";

            return;
        }


        let summary = [];


        if (departments) {
            summary.push(
                `${departments} department${departments > 1 ? "s" : ""}`
            );
        }


        if (employees) {
            summary.push(
                `${employees} employee${employees > 1 ? "s" : ""}`
            );
        }


        if (custom) {
            summary.push(
                `${custom} custom email${custom > 1 ? "s" : ""}`
            );
        }


        recipientCount.textContent = count;

        audienceStatus.textContent =
            summary.join(" · ");

        audienceSummaryTitle.textContent =
            `${summary.join(" + ")} selected`;

        audienceSummaryDescription.textContent =
            `${count} recipient${count !== 1 ? "s" : ""} will receive this message.`;


        if (isBulkSend(count)) {

            sendStateTitle.textContent =
                "Admin approval required";

            sendStateDescription.textContent =
                "Bulk messages are queued for review before delivery.";

        } else {

            sendStateTitle.textContent =
                "Ready to send";

            sendStateDescription.textContent =
                "This message can be sent immediately.";

        }

    }


    /* =====================================================
       LIVE PREVIEW
    ===================================================== */

    function updatePreview() {

        const subject =
            subjectInp.value.trim();

        const body =
            bodyInp.value.trim();


        previewSubject.textContent =
            subject || "Your announcement subject";


        if (!body) {

            previewBody.innerHTML = `
                <div class="preview-placeholder">
                    <div class="placeholder-icon">✦</div>
                    <strong>Your message will appear here</strong>
                    <span>Start typing to see a live preview.</span>
                </div>
            `;

            return;
        }


        /*
         * Task 4 explicitly supports HTML message bodies,
         * so render the authored HTML inside the preview.
         */
        previewBody.innerHTML = body;

    }


    /* =====================================================
       CHARACTER COUNT
    ===================================================== */

    function updateCharacterCount() {

        const length =
            bodyInp.value.length;

        characterCount.textContent =
            `${length.toLocaleString()} characters`;

    }


    /* =====================================================
       TOGGLE ALL EMPLOYEES
    ===================================================== */

    function toggleRecipientMode() {

        if (sendToAll.checked) {

            recipientGroups.style.opacity = ".35";
            recipientGroups.style.pointerEvents = "none";

            deptChoices.disable();
            empChoices.disable();

            customEmails.disabled = true;

        } else {

            recipientGroups.style.opacity = "1";
            recipientGroups.style.pointerEvents = "auto";

            deptChoices.enable();
            empChoices.enable();

            customEmails.disabled = false;

        }

        updateAudience();

    }


    /* =====================================================
       TEMPLATE LOADING
    ===================================================== */

    templateSelect.addEventListener(
        "change",
        async function () {

            if (!this.value) {

                subjectInp.value = "";
                bodyInp.value = "";

                updatePreview();
                updateCharacterCount();

                return;
            }


            try {

                const response =
                    await fetch(
                        `/hrms/announcements/templates/${this.value}`
                    );


                const data =
                    await response.json();


                if (data && !data.error) {

                    subjectInp.value =
                        data.subject || "";

                    bodyInp.value =
                        data.body_html || "";


                    updatePreview();
                    updateCharacterCount();

                }

            } catch (error) {

                console.error(
                    "Unable to load template:",
                    error
                );

            }

        }
    );


    clearTemplate.addEventListener(
        "click",
        function () {

            templateSelect.value = "";

            subjectInp.value = "";
            bodyInp.value = "";

            updatePreview();
            updateCharacterCount();

        }
    );


    /* =====================================================
       LISTENERS
    ===================================================== */

    sendToAll.addEventListener(
        "change",
        toggleRecipientMode
    );


    subjectInp.addEventListener(
        "input",
        updatePreview
    );


    bodyInp.addEventListener(
        "input",
        function () {

            updatePreview();
            updateCharacterCount();

        }
    );


    customEmails.addEventListener(
        "input",
        updateAudience
    );


    departmentSelect.addEventListener(
        "change",
        updateAudience
    );


    singleEmail.addEventListener(
        "change",
        updateAudience
    );


    /* =====================================================
       SEND MODAL
    ===================================================== */

    const sendModal =
        document.getElementById("sendModal");

    const closeSendModal =
        document.getElementById("closeSendModal");

    const cancelSend =
        document.getElementById("cancelSend");

    const confirmSend =
        document.getElementById("confirmSend");

    const modalRecipientCount =
        document.getElementById("modalRecipientCount");



    const modalApprovalState =
        document.getElementById("modalApprovalState");

    const modalWarning =
        document.getElementById("modalWarning");


    function closeModal() {

        sendModal.classList.remove("show");

    }


    const QUOTA_USED  = cfg.quotaUsed || 0;
    const QUOTA_LIMIT = cfg.quotaLimit || 500;

    // Track current over-quota send mode for the two extra buttons
    let _currentOverQuotaRemaining = 0;

    function openModal() {

        const count = calculateRecipientCount();
        const bulk  = isBulkSend(count);
        const afterSend = QUOTA_USED + count;
        const overCap   = afterSend > QUOTA_LIMIT;
        const remaining = Math.max(0, QUOTA_LIMIT - QUOTA_USED);
        _currentOverQuotaRemaining = remaining;

        modalRecipientCount.textContent = count;

        document.getElementById("modalQuotaUsed").textContent =
            QUOTA_USED + " / " + QUOTA_LIMIT;

        const afterEl = document.getElementById("modalQuotaAfter");
        afterEl.textContent = afterSend + " / " + QUOTA_LIMIT;
        afterEl.style.color = overCap ? "#ef4444" : "#10b981";

        modalApprovalState.textContent = bulk ? "Admin approval" : "Immediate";

        // Button visibility
        const normalBtn       = document.getElementById("confirmSend");
        const withinQuotaBtn  = document.getElementById("confirmWithinQuota");
        const queueAllBtn     = document.getElementById("confirmQueueAll");
        const withinCount     = document.getElementById("withinQuotaCount");

        if (overCap && remaining > 0) {
            // Show both over-quota options, hide normal button
            normalBtn.style.display      = "none";
            withinQuotaBtn.style.display = "";
            queueAllBtn.style.display    = "";
            withinCount.textContent = remaining;

            const over = afterSend - QUOTA_LIMIT;
            modalWarning.textContent =
                "⚠️ This send exceeds today\'s Gmail cap by " + over + " email" +
                (over === 1 ? "" : "s") + ". Choose how to proceed below.";
            modalWarning.style.background  = "rgba(239,68,68,0.15)";
            modalWarning.style.borderColor = "rgba(239,68,68,0.4)";
            modalWarning.style.color       = "#fca5a5";

        } else if (overCap && remaining === 0) {
            // Quota fully exhausted — only queue-all option makes sense
            normalBtn.style.display      = "none";
            withinQuotaBtn.style.display = "none";
            queueAllBtn.style.display    = "";

            modalWarning.textContent =
                "⚠️ Today\'s Gmail quota is fully used (" + QUOTA_LIMIT + " / " + QUOTA_LIMIT + "). " +
                "All messages will be queued and sent from tomorrow.";
            modalWarning.style.background  = "rgba(239,68,68,0.15)";
            modalWarning.style.borderColor = "rgba(239,68,68,0.4)";
            modalWarning.style.color       = "#fca5a5";

        } else {
            // Normal path — within quota
            normalBtn.style.display      = "";
            withinQuotaBtn.style.display = "none";
            queueAllBtn.style.display    = "none";

            if (bulk) {
                modalWarning.textContent = "This message is a bulk send. It will enter the Admin approval queue before Gmail delivery.";
            } else {
                modalWarning.textContent = "This message targets a single recipient and can be sent immediately.";
            }
            modalWarning.style.background  = "";
            modalWarning.style.borderColor = "";
            modalWarning.style.color       = "";
        }

        sendModal.classList.add("show");

    }


    sendBtn.addEventListener(
        "click",
        function () {

            if (!subjectInp.value.trim()) {

                showToast("Please enter an email subject.", "error");

                subjectInp.focus();

                return;
            }


            if (!bodyInp.value.trim()) {

                showToast("Please enter a message.", "error");

                bodyInp.focus();

                return;
            }


            const departments =
                getSelectedDepartmentNames();

            const employees =
                getSelectedEmployeeEmails();

            const custom =
                getCustomEmails();


            if (
                !sendToAll.checked &&
                departments.length === 0 &&
                employees.length === 0 &&
                custom.length === 0
            ) {

                showToast("Please select at least one recipient.", "error");

                return;
            }


            openModal();

        }
    );


    closeSendModal.addEventListener(
        "click",
        closeModal
    );


    cancelSend.addEventListener(
        "click",
        closeModal
    );


    sendModal.addEventListener(
        "click",
        function (event) {

            if (event.target === sendModal) {
                closeModal();
            }

        }
    );


    /* =====================================================
       FINAL SEND  (shared helper)
    ===================================================== */

    async function doSend(extraFields, btn, originalLabel) {
        btn.disabled = true;
        btn.innerHTML = `<span class="spinner"></span> Sending...`;

        const formData = new FormData(form);
        for (const [k, v] of Object.entries(extraFields || {})) {
            formData.append(k, v);
        }

        try {
            const response = await fetch("/hrms/announcements/send", {
                method: "POST",
                body: formData
            });
            const data = await response.json();

            if (data.success) {
                btn.innerHTML = "Success!";
                btn.style.background  = "#22c55e";
                btn.style.borderColor = "#22c55e";
                btn.style.color       = "#ffffff";
                modalWarning.innerHTML =
                    `<strong style="color:#4ade80;">${data.message || "Announcement queued successfully."}</strong>`;
                setTimeout(() => location.reload(), 1500);
                return;
            }

            modalWarning.innerHTML =
                `<strong style="color:#ef4444;">Error: ${data.error || "Unknown error."}</strong>`;
            btn.disabled = false;
            btn.textContent = originalLabel;

        } catch (err) {
            console.error(err);
            modalWarning.innerHTML =
                `<strong style="color:#ef4444;">Server error while sending the announcement.</strong>`;
            btn.disabled = false;
            btn.textContent = originalLabel;
        }
    }

    /* Normal path */
    confirmSend.addEventListener("click", () =>
        doSend({}, confirmSend, "Confirm & Send")
    );

    /* Over-quota: trim list to remaining quota */
    document.getElementById("confirmWithinQuota").addEventListener("click", function () {
        doSend(
            { limit_to: _currentOverQuotaRemaining },
            this,
            "Send within quota (" + _currentOverQuotaRemaining + ")"
        );
    });

    /* Over-quota: queue all, scheduler drains naturally across days */
    document.getElementById("confirmQueueAll").addEventListener("click", function () {
        doSend({}, this, "Queue all \u2014 overflow sends tomorrow");
    });


    /* =====================================================
       INITIAL STATE
    ===================================================== */

    toggleRecipientMode();
    updatePreview();
    updateCharacterCount();
    updateAudience();

});