;; dump_portpilot.il — 导出 port_pilot/OPA_D 的实例与尺寸，便于核对"新原理图"
(printf "\n=== DUMP PORT_PILOT START\n")
(let (cv)
  (setq cv (dbOpenCellViewByType "port_pilot" "OPA_D" "schematic" "schematic" "r"))
  (if (null cv)
      (printf "ERROR: 打不开 port_pilot/OPA_D/schematic\n")
      (progn
        (printf "lib=port_pilot cell=OPA_D view=schematic instances=%d\n" (length cv~>instances))
        (foreach inst cv~>instances
          (printf "INST %-6s master=%s/%s/%s w=%L l=%L fingers=%L m=%L\n"
                  inst~>name inst~>master~>libName inst~>master~>cellName inst~>master~>viewName
                  (dbGet inst "w") (dbGet inst "l")
                  (dbGet inst "fingers") (dbGet inst "m")))))
  (dbClose cv))
(printf "=== DUMP PORT_PILOT DONE\n")
(exit)