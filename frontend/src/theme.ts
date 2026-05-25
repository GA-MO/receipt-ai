import { createTheme, type MantineColorsTuple, rem } from "@mantine/core";
import { DatePickerInput } from "@mantine/dates";
import { Calendar } from "lucide-react";
import { createElement } from "react";

// Indigo palette tuned to match the showcase (accent-500 = #6366f1)
const indigo: MantineColorsTuple = [
  "#eef2ff",
  "#e0e7ff",
  "#c7d2fe",
  "#a5b4fc",
  "#818cf8",
  "#6366f1",
  "#4f46e5",
  "#4338ca",
  "#3730a3",
  "#312e81",
];

export const theme = createTheme({
  primaryColor: "indigo",
  colors: { indigo },
  fontFamily: "IBM Plex Sans Thai, system-ui, sans-serif",
  defaultRadius: "md",
  cursorType: "pointer",
  headings: {
    fontFamily: "IBM Plex Sans Thai, system-ui, sans-serif",
    fontWeight: "700",
    sizes: {
      h1: { fontSize: rem(32), lineHeight: "1.2" },
      h2: { fontSize: rem(24), lineHeight: "1.3" },
      h3: { fontSize: rem(20), lineHeight: "1.4" },
      h4: { fontSize: rem(18), lineHeight: "1.4" },
    },
  },
  components: {
    Paper: {
      defaultProps: {
        shadow: "xs",
        radius: "lg",
        withBorder: true,
      },
    },
    Card: {
      defaultProps: {
        shadow: "xs",
        radius: "lg",
        withBorder: true,
      },
    },
    Button: {
      defaultProps: {
        radius: "md",
      },
    },
    ActionIcon: {
      defaultProps: {
        radius: "md",
      },
    },
    TextInput: {
      defaultProps: {
        radius: "md",
      },
    },
    NumberInput: {
      defaultProps: {
        radius: "md",
      },
    },
    Select: {
      defaultProps: {
        radius: "md",
      },
    },
    Autocomplete: {
      defaultProps: {
        radius: "md",
      },
    },
    Badge: {
      defaultProps: {
        radius: "xl",
      },
    },
    Modal: {
      defaultProps: {
        radius: "lg",
      },
    },
    Tabs: {
      defaultProps: {
        radius: "md",
      },
    },
    DatePickerInput: {
      defaultProps: {
        radius: "md",
        leftSection: createElement(Calendar, { size: 16 }),
        leftSectionPointerEvents: "none" as const,
      },
    },
  },
});
