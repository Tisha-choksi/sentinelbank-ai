"use client";

import { useMemo } from "react";
import dynamic from "next/dynamic";
import type { ElementDefinition, StylesheetJsonBlock } from "cytoscape";
import type { Alert, Transaction } from "@/lib/types";

// Cytoscape touches the DOM directly on mount and has no useful SSR output,
// so it's loaded client-side only.
const CytoscapeComponent = dynamic(() => import("react-cytoscapejs"), {
  ssr: false,
  loading: () => (
    <div className="flex h-[520px] items-center justify-center text-sm text-ink-muted">
      Loading graph...
    </div>
  ),
});

const RULE_COLOR: Record<string, string> = {
  TXN_HIGH_VALUE: "#3987e5",
  TXN_VELOCITY: "#d95926",
  TXN_CIRCULAR_FLOW: "#199e70",
};

function buildElements(
  transactions: Transaction[],
  alerts: Alert[]
): ElementDefinition[] {
  const alertByTxnId = new Map(alerts.map((a) => [a.transaction_id, a]));
  const accountIds = new Set<string>();
  const elements: ElementDefinition[] = [];

  for (const t of transactions) {
    accountIds.add(t.from_account);
    accountIds.add(t.to_account);
  }
  for (const account of accountIds) {
    elements.push({
      data: { id: account, label: account },
      classes: "account",
    });
  }
  for (const t of transactions) {
    const alert = alertByTxnId.get(t.id);
    elements.push({
      data: {
        id: `txn-${t.id}`,
        source: t.from_account,
        target: t.to_account,
        label: `${t.currency} ${Number(t.amount).toLocaleString()}`,
        flagged: Boolean(alert),
        color: alert ? RULE_COLOR[alert.rule_code] ?? "#898781" : "#52514e",
      },
      classes: alert ? "flagged" : "normal",
    });
  }
  return elements;
}

const STYLESHEET: StylesheetJsonBlock[] = [
  {
    selector: "node.account",
    style: {
      "background-color": "#222220",
      "border-width": 1.5,
      "border-color": "#383835",
      label: "data(label)",
      color: "#f0efec",
      "font-size": 10,
      "text-valign": "bottom",
      "text-margin-y": 6,
      width: 26,
      height: 26,
    },
  },
  {
    selector: "edge",
    style: {
      width: 2,
      "line-color": "data(color)",
      "target-arrow-color": "data(color)",
      "target-arrow-shape": "triangle",
      "curve-style": "bezier",
      label: "data(label)",
      "font-size": 8,
      color: "#c3c2b7",
      "text-rotation": "autorotate",
      "text-margin-y": -6,
    },
  },
  {
    selector: "edge.flagged",
    style: {
      width: 3,
    },
  },
];

export function TransactionGraph({
  transactions,
  alerts,
}: {
  transactions: Transaction[];
  alerts: Alert[];
}) {
  const elements = useMemo(
    () => buildElements(transactions, alerts),
    [transactions, alerts]
  );

  return (
    <CytoscapeComponent
      elements={elements}
      stylesheet={STYLESHEET}
      layout={{ name: "cose", animate: false, padding: 40 }}
      style={{ width: "100%", height: "520px" }}
      cy={(cy) => {
        cy.on("tap", "node", (evt) => {
          evt.target.neighborhood().addClass("highlighted");
        });
      }}
    />
  );
}
