;; pilot_run.il — 07B 试点：建库 → 放一个源 PDK 管子 → 转换 → 套尺寸 → 打印结果
;; 用法：cd /home/IC && timeout 300 virtuoso -nograph < /tmp/pilot_run.il
(printf "\n=== PILOT START\n")

;; 1) 建目标库（已存在则忽略错误）
(if (ddGetObj "port_pilot")
    (printf "lib port_pilot 已存在\n")
    (ddCreateLib "port_pilot" "/home/IC/port_pilot"))

;; 2) 建 cell + 放一个源 PDK 实例
(let (cv inst)
  (setq cv (dbOpenCellViewByType "port_pilot" "pilot_mos" "schematic" "schematic" "w"))
  (if (null cv)
      (printf "ERROR: 无法创建 schematic\n")
      (progn
        (setq inst (dbCreateInstByMasterName cv "smic18ee" "n18e2r" "symbol" "M1" 0:0 "R0"))
        (if (null inst)
            (printf "ERROR: 无法放置 smic18ee/n18e2r 实例\n")
            (progn
              (dbSet inst "w" "2e-6")
              (dbSet inst "l" "0.5e-6")
              (printf "源实例: %s master=%s/%s w=%L l=%L\n"
                      inst~>name inst~>master~>libName inst~>master~>cellName
                      inst~>w inst~>l)
              (schCheck cv)
              (dbSave cv)
              )))))

;; 3) 转换（换 master）
(load "/tmp/abConvertComponentParams.il")
(load "/tmp/abInvokeCdfCallbacks.il")
(let (cv changed)
  (setq cv (dbOpenCellViewByType "port_pilot" "pilot_mos" "schematic" "schematic" "a"))
  (setq changed (abConvertComponentParams "/tmp/pilot_conv.config" cv))
  (printf "转换结果 changed=%L\n" changed)
  (foreach i cv~>instances
    (printf "  after convert: %s master=%s/%s\n"
            i~>name i~>master~>libName i~>master~>cellName))
  (dbSave cv))

;; 4) 套尺寸
(load "/tmp/apply_sizes.il")
(let (cv ok)
  (setq cv (dbOpenCellViewByType "port_pilot" "pilot_mos" "schematic" "schematic" "a"))
  (setq ok (abApplySizes "/tmp/pilot_sizes.csv" ?cellView cv
                         ?paramMap (list (list "w" "w") (list "l" "l")
                                         (list "nf" "fingers") (list "m" "m"))))
  (printf "apply_sizes ok=%L\n" ok)
  (foreach i cv~>instances
    (printf "  final: %s master=%s/%s w=%L l=%L fingers=%L m=%L\n"
            i~>name i~>master~>libName i~>master~>cellName
            i~>w i~>l i~>fingers i~>m))
  (schCheck cv)
  (dbSave cv))

(printf "=== PILOT DONE\n")
(exit)
