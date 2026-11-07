"use client";

import { useTranslation } from "react-i18next";

export function SettingsHeader() {
  const { t } = useTranslation("common");
  return (
    <section className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
      <div className="space-y-1">
        <h1 className="text-2xl font-semibold tracking-tight">{t("nav.settings")}</h1>
      </div>
    </section>
  );
}
